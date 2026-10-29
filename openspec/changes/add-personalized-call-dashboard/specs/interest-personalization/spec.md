# Spec Delta

## Purpose

Selects and presents the day's stories according to each user's stated interests, while keeping unverified or politically sensitive claims honestly attributed and keeping compute cost independent of the number of users.

## ADDED Requirements

### Requirement: Interest-based selection
The system SHALL build each user's briefing only from stories that match that user's interests and meet the minimum importance threshold, ordered by importance, never exceeding the maximum story count.

#### Scenario: Matching stories exist
- **WHEN** a user's interests are "tech" and "stocks" and qualifying tech and markets stories exist
- **THEN** the briefing contains only those stories, highest importance first

#### Scenario: Nothing qualifies
- **WHEN** no story matching the user's interests meets the threshold
- **THEN** the briefing is a short quiet-day message and is not padded with unrelated or low-score stories

### Requirement: Free-text interest understanding
The system SHALL translate free-text interests into topics and keywords when the profile is saved, and SHALL fall back to general top stories with a visible notice when the text cannot be understood.

#### Scenario: Understood text
- **WHEN** a user writes "foreign policy and what China is doing near India"
- **THEN** the profile is tagged with geopolitics and the keywords are used to boost matching stories

#### Scenario: Not understood
- **WHEN** the text maps to no known topic or keyword
- **THEN** the user is shown a notice and receives general top stories

### Requirement: Honest handling of unverified claims
The system SHALL attribute each political, legal or otherwise contested claim to its source, SHALL mark claims not yet confirmed as unconfirmed, and SHALL NOT state an alleged cause or motive as fact.

#### Scenario: Alleged foreign funding
- **WHEN** sources link a domestic protest to foreign funding without evidence
- **THEN** the script says who is making the claim, that it is unconfirmed, and what is actually established

#### Scenario: Single-source story
- **WHEN** a story has only one low-tier source
- **THEN** the script says it is reported by that source and not yet corroborated

### Requirement: Cost independent of user count
The system SHALL perform ingestion, clustering, scoring and context generation once per pipeline run regardless of users, and SHALL generate each story's spoken text at most once per language per development of that story.

#### Scenario: Many users, same story
- **WHEN** 50 users with overlapping interests and the same language are due for calls
- **THEN** each story's spoken text for that language is generated once and reused for all 50

### Requirement: Repeat suppression
The system SHALL omit a story from a user's briefing if it was already delivered to that user and has had no minor or major development since.

#### Scenario: No new development
- **WHEN** a story was in yesterday's call and its change kind is `repeat`
- **THEN** it is not included today
