# Spec Delta

## Purpose

Decides when each user is called, guarantees one call per user per day, and degrades predictably under load, restarts and stale data.

## ADDED Requirements

### Requirement: Per-user daily call time
The system SHALL ring each active, consenting, unpaused user once per day at their chosen local time, within 1 minute of that time under normal operation.

#### Scenario: On-time ring
- **WHEN** a user's call time is 21:30 Asia/Kolkata and the system is running
- **THEN** the user is rung between 21:30 and 21:31 IST

#### Scenario: Changed time
- **WHEN** a user changes their time from 21:30 to 20:00 before 20:00 today
- **THEN** the next ring is at 20:00 today

### Requirement: At most one scheduled call per day
The system SHALL ring a user at most once per local calendar day for the scheduled call, including across restarts and duplicate scheduler ticks.

#### Scenario: Restart mid-window
- **WHEN** the system restarts at 21:30:20 after already ringing a user at 21:30:00
- **THEN** the user is not rung a second time

### Requirement: Script readiness
The system SHALL have the user's briefing assembled before ringing, and SHALL NOT deliver stories outside the freshness window.

#### Scenario: Pipeline stale
- **WHEN** no fresh pipeline run exists within the freshness window at ring time
- **THEN** the user receives a short message that today's briefing is unavailable instead of old stories

### Requirement: Missed call handling
The system SHALL mark a ring as missed if not answered within 10 minutes, SHALL send at most one reminder, and SHALL show missed calls on the dashboard.

#### Scenario: Unanswered
- **WHEN** a user does not answer for 10 minutes
- **THEN** the ring is marked missed and no further automatic ring is made that day beyond one reminder

### Requirement: Concurrency limit
The system SHALL cap simultaneous live calls at a configured limit and SHALL defer excess users by at most 5 minutes rather than dropping them.

#### Scenario: Burst at popular time
- **WHEN** more users are due at 21:30 than the concurrency limit allows
- **THEN** the remaining users are rung in later slots within 5 minutes and none are skipped

### Requirement: Paused and unconsented users are never rung
The system SHALL NOT ring a user who is paused, deleted, or without recorded consent.

#### Scenario: Paused user at call time
- **WHEN** a paused user's call time arrives
- **THEN** no ring is made
