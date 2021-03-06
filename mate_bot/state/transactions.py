#!/usr/bin/env python3

"""
MateBot money transaction (sending/receiving) helper library
"""

import time
import typing

import pytz as _tz
import tzlocal as _local_tz

from . import user
from . import dbhelper as _db


class Transaction:
    """
    Money transactions between two users

    Note that a transaction will not be committed and stored in
    persistent storage until the .commit() method was called!
    """

    def __init__(
            self,
            src: user.BaseBotUser,
            dst: user.BaseBotUser,
            amount: int,
            reason: typing.Optional[str] = None
    ):
        """
        :param src: user that sends money to someone else
        :type src: user.BaseBotUser
        :param dst: user that receives money from someone else
        :type dst: user.BaseBotUser
        :param amount: money measured in Cent (must always be positive!)
        :type amount: int
        :param reason: optional description of / reason for the transaction
        :type reason: str or None
        :raises ValueError: when amount is not positive
        :raises TypeError: when src or dst are no BaseBotUser objects or subclassed thereof
        """

        if amount <= 0:
            raise ValueError("Not a positive amount!")
        if not isinstance(src, user.BaseBotUser) or not isinstance(dst, user.BaseBotUser):
            raise TypeError("Expected BaseBotUser or its subclasses!")

        self._src = src
        self._dst = dst
        self._amount = int(amount)
        self._reason = reason

        self._committed = False
        self._id = None

    def __bool__(self) -> bool:
        return self._committed

    def get(self) -> typing.Optional[int]:
        """
        Return the internal ID of the transaction, if available (after committing)

        :return: internal ID of the transaction, if available
        :rtype: typing.Optional[int]
        """

        if self._committed:
            return self._id

    @property
    def src(self) -> user.BaseBotUser:
        """
        Get the sender of a transaction
        """

        return self._src

    @property
    def dst(self) -> user.BaseBotUser:
        """
        Get the receiver of a transaction
        """

        return self._dst

    @property
    def amount(self) -> int:
        """
        Get the height of the transaction (amount)
        """

        return self._amount

    @property
    def reason(self) -> typing.Optional[str]:
        """
        Get the optional reason for the transaction (description)
        """

        return self._reason

    @property
    def committed(self) -> bool:
        """
        Get the flag whether the transaction has been committed yet
        """

        return self._committed

    def commit(self) -> None:
        """
        Fulfill the transaction and store it in the database persistently

        :raises RuntimeError: when amount is negative or zero
        :return: None
        """

        if self._amount < 0:
            raise RuntimeError("No negative transactions!")
        if self._amount == 0:
            raise RuntimeError("Empty transaction!")

        if not self._committed and self._id is None:
            connection = None
            try:
                self._src.update()
                self._dst.update()

                connection = _db.execute_no_commit(
                    "INSERT INTO transactions (sender, receiver, amount, reason) "
                    "VALUES (%s, %s, %s, %s)",
                    (self._src.uid, self._dst.uid, self._amount, self._reason)
                )[2]

                rows, values, _ = _db.execute_no_commit(
                    "SELECT LAST_INSERT_ID()",
                    connection=connection
                )
                if rows == 1:
                    self._id = values[0]["LAST_INSERT_ID()"]

                _db.execute_no_commit(
                    "UPDATE users SET balance=%s WHERE id=%s",
                    (self._src.balance - self.amount, self._src.uid),
                    connection=connection
                )
                _db.execute_no_commit(
                    "UPDATE users SET balance=%s WHERE id=%s",
                    (self._dst.balance + self.amount, self._dst.uid),
                    connection=connection
                )

                connection.commit()

                self._src.update()
                self._dst.update()
                self._committed = True

            finally:
                if connection:
                    connection.close()


class TransactionLog:
    """
    Transaction history for a specific user based on the logs in the database

    When instantiating a TransactionLog object, one can filter the
    transactions based on their "direction" using the `mode` keyword.
    The default value of zero means that all transactions will be used.
    Any negative integer means that only negative operations (the specified
    user is the sender) will be used while any positive integer means that
    only positive operations will be used (the specified user is the receiver).
    """

    DEFAULT_NULL_REASON_REPLACE = "<no description>"

    def __init__(self, uid: typing.Union[int, user.BaseBotUser], mode: int = 0):
        """
        :param uid: internal user ID or BaseBotUser instance (or subclass thereof)
        :type uid: int or user.BaseBotUser
        :param mode: direction of listed transactions
        :type mode: int
        """

        if isinstance(uid, int):
            self._uid = uid
        elif isinstance(uid, user.BaseBotUser):
            self._uid = uid.uid
        else:
            raise TypeError("UID of bad type {}".format(type(uid)))

        self._mode = mode

        if self._mode < 0:
            rows, self._log = _db.execute(
                "SELECT * FROM transactions WHERE sender=%s",
                (self._uid,)
            )
        elif self._mode > 0:
            rows, self._log = _db.execute(
                "SELECT * FROM transactions WHERE receiver=%s",
                (self._uid,)
            )
        else:
            rows, self._log = _db.execute(
                "SELECT * FROM transactions WHERE sender=%s OR receiver=%s",
                (self._uid, self._uid)
            )

        self._valid = True
        if rows == 0 and user.BaseBotUser.get_tid_from_uid(self._uid) is None:
            self._valid = False
        if len(self._log) == 0:
            self._log = []
        self._valid = self._valid and self.validate()

    def to_string(self, localized: bool = True) -> str:
        """
        Return a pretty formatted version of the transaction log

        :param localized: switch whether the timestamps should be in localtime or UTC
        :type localized: bool
        :return: fully formatted string including all transactions of a user
        :rtype: str
        """

        logs = []
        for entry in self._log:
            amount = entry["amount"] / 100
            reason = entry["reason"]
            if entry["reason"] is None:
                reason = self.DEFAULT_NULL_REASON_REPLACE

            if entry["receiver"] == self._uid:
                direction = "<<"
                partner = entry["sender"]
            elif entry["sender"] == self._uid:
                direction = ">>"
                partner = entry["receiver"]
                amount = -amount
            else:
                raise RuntimeError

            ts = _tz.utc.localize(entry["registered"])
            if localized:
                ts = ts.astimezone(_local_tz.get_localzone())

            logs.append(
                "{}: {:>+6.2f}: me {} {:<11} :: {}".format(
                    time.strftime("%d.%m.%Y %H:%M", ts.timetuple()),
                    amount,
                    direction,
                    user.BaseBotUser.get_name_from_uid(partner),
                    reason
                )
            )

        if len(logs) > 0:
            return "\n".join(logs)
        return ""

    def to_json(self) -> typing.List[typing.Dict[str, typing.Union[int, str]]]:
        """
        Return a JSON-serializable list of transaction entries

        Note that the datetime objects will be converted to integers representing UNIX timestamps.

        :return: list
        """

        result = []
        for entry in self._log:
            result.append(entry.copy())
            result[-1]["registered"] = int(result[-1]["registered"].timestamp())
        return result

    def validate(self, start: int = 0) -> typing.Optional[bool]:
        """
        Validate the history and verify integrity (full history since start of the logs)

        This method is only useful for full history checks and therefore
        returns None when the mode was set to a non-zero value.

        :param start: balance of the user when it was first created (should be zero)
        :type start: int
        :return: history's validity
        """

        if self._mode != 0:
            return None

        current = user.MateBotUser(self._uid).balance

        for entry in self._log:
            if entry["receiver"] == self._uid:
                start += entry["amount"]
            elif entry["sender"] == self._uid:
                start -= entry["amount"]
            else:
                raise RuntimeError

        return start == current

    @property
    def uid(self) -> int:
        """
        Get the internal user ID for which the log was created
        """

        return self._uid

    @property
    def valid(self) -> bool:
        """
        Get the valid flag which is set when the transaction log seems to be complete and correct
        """

        return self._valid

    @property
    def history(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        Get the raw data of the user's transaction history
        """

        return self._log
