#!/usr/bin/env python3

"""
MateBot project-wide exception classes
"""


class MateBotException(Exception):
    """
    Base class for all project-wide exceptions
    """


class DesignViolation(MateBotException):
    """
    Exception when a situation is not intended by design while being a valid state

    This exception is likely to occur when a database operation
    fails due to specific checks. It ensures e.g. that no
    second community user exists in a database or that a user
    is participating in a collective operation at most one time.
    """


class ParsingError(MateBotException):
    """
    Exception raised when the argument parser throws an error

    This is likely to happen when a user messes up the syntax of a
    particular command. Instead of exiting the program, this exception
    will be raised. You may use it's string representation to gain
    additional information about what went wrong. This allows a user
    to correct its command, in case this caused the parser to fail.
    """
