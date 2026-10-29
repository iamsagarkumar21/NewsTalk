# Spec Delta

## Purpose

Delivers the briefing as an interruptible voice conversation, ringing the user through a free notification channel and connecting them through an authenticated browser call, with real phone calls available only to verified numbers.

## ADDED Requirements

### Requirement: Ring notification
The system SHALL notify the user at their call time through their linked notification channel with a single-action "Answer" link to the call page.

#### Scenario: Linked channel
- **WHEN** a user has linked Telegram and their call time arrives
- **THEN** they receive a message addressed by call name with an Answer button

#### Scenario: No channel linked
- **WHEN** a user has no linked channel
- **THEN** the dashboard shows a prompt to link one and the ring is recorded as undeliverable

### Requirement: Authenticated call connection
The system SHALL accept a voice connection only with a signed, single-use token bound to one user and one briefing that expires 10 minutes after issue.

#### Scenario: Valid token
- **WHEN** the user taps Answer within 10 minutes
- **THEN** the call connects to that user's briefing

#### Scenario: Missing, reused or expired token
- **WHEN** a connection presents no token, a used token or an expired token
- **THEN** the connection is refused and no briefing content is sent

### Requirement: Interruptible conversation
The system SHALL stop speaking within 300 ms of detecting the user speaking, answer the question using only that user's briefing and story context, and resume or end on request.

#### Scenario: Barge-in
- **WHEN** the user says "ruko, ye kya hai?" mid-sentence
- **THEN** speech stops, a short grounded answer is spoken, and the briefing can continue

#### Scenario: Goodbye
- **WHEN** the user says "bye"
- **THEN** a closing line is spoken and the call ends

### Requirement: Personal address
The system SHALL greet the user by their call name and state the approximate briefing length at the start of the call.

#### Scenario: Greeting
- **WHEN** a call connects for call name "Sagar bhai"
- **THEN** the first spoken line uses "Sagar bhai"

### Requirement: Phone calls only to verified numbers
The system SHALL place a real phone call only to a number the user has verified by answering a verification call and confirming, and only while phone delivery is enabled for that user.

#### Scenario: Unverified number
- **WHEN** a user enters a phone number without completing verification
- **THEN** no briefing call is placed to that number

#### Scenario: Verified and enabled
- **WHEN** a verified user has phone delivery enabled
- **THEN** the scheduled call is placed to that number instead of a notification

### Requirement: Text-only records
The system SHALL store call text (script and Q&A) for 30 days and SHALL NOT store call audio.

#### Scenario: After a call
- **WHEN** a call ends
- **THEN** the transcript is available on the dashboard and no audio file exists
