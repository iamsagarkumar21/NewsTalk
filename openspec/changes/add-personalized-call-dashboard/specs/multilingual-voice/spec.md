# Spec Delta

## Purpose

Lets users hear and speak with Jiya in English, Hinglish or Hindi, and ensures the whole product works at zero provider cost for demo use.

## ADDED Requirements

### Requirement: Supported languages
The system SHALL support English (default), Hinglish (Hindi–English mix) and Hindi for the spoken script, speech output, speech recognition and fixed phrases.

#### Scenario: Default language
- **WHEN** a user never changes language
- **THEN** all spoken output is in Indian English

#### Scenario: Hinglish selected
- **WHEN** a user selects Hinglish
- **THEN** the briefing is conversational Hindi with English technical and proper terms kept in English, in the register of a friend rather than a news anchor

### Requirement: Intelligible speech output per language
The system SHALL speak each language with a voice that pronounces it intelligibly, including embedded English terms and proper names, and SHALL fall back to a working voice with a notice instead of silence if the preferred voice fails.

#### Scenario: Mixed-script sentence
- **WHEN** a Hinglish script contains "Cloudflare ने Deno acquire कर लिया"
- **THEN** it is spoken with Hindi grammar and English terms pronounced as English words

#### Scenario: Voice provider failure
- **WHEN** the preferred voice provider is unavailable
- **THEN** the call continues on a fallback voice and the user is told once

### Requirement: Recognition of code-switched speech
The system SHALL recognize user speech in their selected language including English words mixed within it.

#### Scenario: Mixed question
- **WHEN** a Hinglish user asks "Supabase Deno se kis runtime pe jayega?"
- **THEN** the question is understood and answered in the same register

### Requirement: Localized fixed phrases
The system SHALL localize greeting, quiet-day, Q&A invitation and goodbye lines per language and SHALL keep Jiya's warm casual personality in each.

#### Scenario: Hindi goodbye
- **WHEN** a Hindi-language user says goodbye
- **THEN** the closing line is in Hindi

### Requirement: Zero-cost default operation
The system SHALL operate all three languages end to end using only free-tier or free services when no paid keys are configured, with paid providers selectable by configuration alone.

#### Scenario: Only free keys set
- **WHEN** only free-tier credentials are present
- **THEN** a demo user in any supported language can complete a full call
