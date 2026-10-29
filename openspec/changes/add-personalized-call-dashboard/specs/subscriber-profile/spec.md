# Spec Delta

## Purpose

Lets an individual user sign in to a dashboard and configure how, when and about what Jiya calls them, with explicit consent and full control over pausing or deleting their data.

## ADDED Requirements

### Requirement: Authenticated access
The system SHALL require a signed-in account (created with a valid invite code, or a Google account) for every profile read or write, and SHALL only expose a user's own profile to that user.

#### Scenario: Unauthenticated visit
- **WHEN** a visitor opens the dashboard without signing in
- **THEN** the system shows only a sign-in prompt and no profile data

#### Scenario: Invalid invite code
- **WHEN** a visitor signs up with an unknown or already exhausted invite code
- **THEN** no account is created

#### Scenario: Cross-user access attempt
- **WHEN** a signed-in user requests another user's profile by id
- **THEN** the system rejects the request and returns no data

### Requirement: Profile fields and defaults
The system SHALL let a user set a call name (1–40 characters), at least one interest, a daily call time in HH:MM at 5-minute granularity, and a language. New profiles SHALL default to language English and timezone Asia/Kolkata.

#### Scenario: New user defaults
- **WHEN** a user signs in for the first time
- **THEN** the form shows language English, timezone Asia/Kolkata and no call time selected

#### Scenario: Invalid input
- **WHEN** a user submits an empty call name or no interests
- **THEN** the system rejects the save and states which field is missing

### Requirement: Interest entry
The system SHALL accept interests as any combination of predefined topic choices and one free-text field of up to 300 characters.

#### Scenario: Free text only
- **WHEN** a user enters "Indian startups and SEBI news" and selects no topics
- **THEN** the system saves the profile and shows which topics it understood from the text

### Requirement: Explicit consent
The system SHALL NOT schedule any call for a user until that user has accepted a consent statement covering automated AI calls and storage of their profile and Q&A text, and SHALL record when consent was given.

#### Scenario: No consent
- **WHEN** a user saves a profile without accepting consent
- **THEN** the profile is stored but the user is not scheduled for calls

#### Scenario: Withdrawal
- **WHEN** a user withdraws consent
- **THEN** no further calls are made to that user

### Requirement: Pause and delete
The system SHALL let a user pause and resume daily calls, and SHALL permanently delete their profile, interests, Q&A history, call history and linked notification channel on request.

#### Scenario: Pause
- **WHEN** a user pauses calls
- **THEN** no call is rung until the user resumes

#### Scenario: Delete account
- **WHEN** a user confirms account deletion
- **THEN** all of that user's stored data is removed and the same Google account starts again as a new user

### Requirement: Test call and transcript
The system SHALL let a user trigger a test call immediately, limited to 3 per day, and SHALL show the text transcript and source links of their most recent briefing.

#### Scenario: Test call limit
- **WHEN** a user requests a fourth test call in one day
- **THEN** the system declines and states the limit

#### Scenario: View transcript
- **WHEN** a user opens the dashboard after a call
- **THEN** the spoken script and the sources of each story are shown
