"""Compatibility exports for the former session coordinator module."""

from .monitor import (
    AgeProgression,
    TimerSynchronizer,
    add_session_args,
    command_watch_session,
    should_remind_villager,
)

__all__ = [
    "TimerSynchronizer",
    "AgeProgression",
    "add_session_args",
    "command_watch_session",
    "should_remind_villager",
]
