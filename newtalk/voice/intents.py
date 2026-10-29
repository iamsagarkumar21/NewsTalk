"""Cheap, LLM-free classification of short spoken replies (English / Hinglish / Hindi).

A person on a call says "hmm", "haan", "ruko", "next"... far more often than they ask a real
question. Sending those to the Q&A model costs a second of silence and an off-topic answer.
"""

from __future__ import annotations

import re

ACK = "ack"  # "ok", "hmm", "haan": keep going
CONTINUE = "continue"  # "go on", "aage bolo"
PAUSE = "pause"  # "wait", "ruko": stop and let me talk
SKIP = "skip"  # "next", "agli khabar"
REPEAT = "repeat"  # "say that again", "dobara"
QUESTION = "question"

_FILLERS = {
    "please", "pls", "jiya", "ji", "na", "yaar", "bhi", "karo", "kar", "do", "de", "zara", "thoda",
    "to", "toh", "so", "just", "can", "you", "u", "me", "it", "that", "this", "the", "a", "one",
    "bhai", "sir", "mam", "ma'am", "hai", "hain", "h", "bas", "abhi",
    "प्लीज़", "प्लीज", "जिया", "जी", "ना", "यार", "भी", "करो", "कर", "दो", "ज़रा", "जरा", "थोड़ा",
    "तो", "है", "हैं", "बस", "अभी", "भाई",
}

_SETS = {
    ACK: {
        "ok", "okay", "k", "kk", "hmm", "hm", "hmmm", "mm", "mhm", "yes", "yeah", "yep", "yup",
        "haan", "han", "ha", "haa", "achha", "accha", "acha", "theek", "thik", "theek hai",
        "thik hai", "right", "sure", "got it", "i see", "understood", "samajh gaya", "samajh gayi",
        "samjha", "samjhi", "bilkul", "correct", "fine", "cool", "nice", "good", "great",
        "thanks", "thank you", "shukriya", "dhanyavaad",
        "हाँ", "हां", "हम्म", "ओके", "ठीक", "ठीक है", "अच्छा", "समझ गया", "समझ गई", "बिल्कुल",
        "सही", "धन्यवाद", "शुक्रिया", "थैंक्स",
    },
    CONTINUE: {
        "go on", "continue", "carry on", "proceed", "go ahead", "keep going", "resume", "next part",
        "aage", "aage badho", "aage bolo", "aage batao", "aage chalo", "chalo", "chalo aage", "bolo",
        "batao", "jaari rakho", "continue karo", "phir", "fir",
        "आगे", "आगे बढ़ो", "आगे बोलो", "आगे बताओ", "चलो", "बोलो", "बताओ", "जारी रखो", "फिर",
    },
    PAUSE: {
        "wait", "hold on", "hold", "one second", "one sec", "just a second", "one minute",
        "just a minute", "stop", "pause", "listen", "hang on", "wait a second", "wait a minute",
        "ruko", "ruk", "ruk jao", "ek second", "ek minute", "ek sec", "ek min", "suno", "rukiye",
        "रुको", "रुक", "रुकिए", "रुक जाओ", "एक सेकंड", "एक मिनट", "सुनो", "ठहरो", "सुनिए",
    },
    SKIP: {
        "skip", "skip it", "skip this", "next", "next one", "next story", "next news", "next item",
        "move on", "another", "something else",
        "agli", "agla", "agli khabar", "agli news", "agli khabar batao", "agli khabar sunao", "agli news sunao", "next khabar", "agli batao", "next batao", "agla wala", "agli wali", "chhodo", "chodo",
        "isse chhodo", "yeh chhodo", "isko chhodo", "dusri", "dusra",
        "अगली", "अगला", "अगली खबर", "अगली न्यूज़", "छोड़ो", "इसे छोड़ो", "दूसरी", "दूसरा",
    },
    REPEAT: {
        "repeat", "repeat that", "say that again", "again", "once more", "say again", "come again",
        "what", "sorry", "pardon", "what did you say", "can't hear", "cant hear",
        "dobara", "dobara bolo", "dobara batao", "phir se", "phir se bolo", "phir se batao",
        "ek aur baar", "kya bola", "kya kaha", "repeat karo", "repeat kijiye", "sunai nahi diya",
        "दोबारा", "दोबारा बोलो", "दोबारा बताओ", "फिर से", "फिर से बोलो", "एक बार और", "क्या बोला",
        "क्या कहा", "रिपीट", "सुनाई नहीं दिया",
    },
}

_TOKEN = re.compile(r"[\wऀ-ॿ']+", re.UNICODE)


def _normalise(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower())]


_WORDS = {intent: {w for ph in phrases for w in ph.split()} for intent, phrases in _SETS.items()}
_ACK_TOKENS = {p for p in _SETS[ACK] if " " not in p}


def _match(core: list[str]) -> str | None:
    phrase = " ".join(core)
    for intent in (PAUSE, SKIP, REPEAT, CONTINUE, ACK):
        if phrase in _SETS[intent]:
            return intent
    if len(core) <= 4:  # "ruko ek minute": every word belongs to one intent's vocabulary
        for intent in (PAUSE, SKIP, REPEAT, CONTINUE):
            if all(t in _WORDS[intent] for t in core):
                return intent
    return None


def classify_utterance(text: str) -> str:
    """One of ACK, CONTINUE, PAUSE, SKIP, REPEAT, QUESTION.

    Only utterances made up *entirely* of command words are commands, so "what does next
    quarter's GDP mean" stays a question.
    """
    tokens = _normalise(text)
    if not tokens or len(tokens) > 6:
        return QUESTION
    core = [t for t in tokens if t not in _FILLERS] or tokens

    found = _match(core)
    if found:
        return found
    # "ok go on", "haan ruko": a leading acknowledgement followed by a command
    while len(core) > 1 and core[0] in _ACK_TOKENS:
        core = core[1:]
        found = _match(core)
        if found:
            return found
    if all(t in _SETS[ACK] for t in core):
        return ACK
    return QUESTION
