# Reminder Trigger Logic

`watch-monitor` is the central coordinator. Readers report what they see; the
coordinator decides when to update the overlay or fire a reminder.

## Timer and Pause State

1. A valid timer OCR read starts a smooth local clock.
2. While the timer changes, the local clock advances without repeatedly
   resynchronizing to OCR.
3. Timer OCR runs every 5 seconds during normal tracking.
4. Two identical timer reads start a pause check. The coordinator then samples
   once per second.
5. A pause is confirmed when at least 3 of 5 pause-check reads equal the last
   changing timer value.
6. While paused, game-time reminders and queue scanning stop, while the overlay
   keeps its current displayed state.
7. The first later timer read that is greater than the paused value resumes and
   reanchors the local timer.

## Age

- The accepted age starts at Age I.
- Normal age reads occur every 5 seconds.
- Age can only advance one level at a time: I to II, II to III, or III to IV.
- A possible advance triggers one-second confirmation reads.
- The next age is accepted only when at least 4 of 5 reads agree.
- An Age I-to-IV false positive cannot skip directly through the progression.
- A current-age read cancels a pending advance; an unrecognized read is neutral.

## Villager Production

- The queue is scanned every second while the game timer is tracking.
- A villager reminder fires after 3 consecutive scans do not find a villager
  in the production row.
- Seeing a villager immediately clears the consecutive-miss count and the
  reminder.
- The reminder is disabled at 20:00 game time and while the game timer is not
  available or confirmed paused.
- The check only answers whether a villager is visible in the queue. It does
  not calculate the number of Town Centers or total villager production rate.

## Research Queue

- Detected research icons are checked every second while the timer is active.
- A technology becomes **in progress** after it appears in at least 6 of the
  latest 10 scans.
- In-progress technology is removed from the actionable reminder list, but it
  can remain visibly indicated on the overlay.
- After 30 seconds of active game time, an in-progress technology is assumed
  complete, marked researched, and removed from the overlay reminder state.
- Pauses do not consume the 30-second completion estimate.

## Technology Availability

- Technologies appear only when their required age and prerequisite upgrades
  are satisfied.
- An unresearched lower-age technology carries forward into later ages.
- Upgrade chains never skip levels: for example, `wood_2` cannot become active
  until `wood_1` is marked researched.
- A next-level technology can be shown muted before its age is reached; it
  becomes actionable once that age is confirmed.

## Reset and User Pause

- Reset clears the session's timer, age progression, research history, and
  debug-event captures, then leaves reminders paused until resumed.
- The user pause control stops live recognition and APM collection without
  erasing the current overlay items. Resuming schedules fresh timer, age, and
  queue checks immediately.
