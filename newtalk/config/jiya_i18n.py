"""Localized fixed phrases and register rules for Jiya (en / hinglish / hi).

Hinglish and Hindi are written in *mixed script*: Hindi words in Devanagari, English words and
proper nouns in Latin. Hindi TTS voices read Devanagari reliably, while Roman-script Hindi
("gir gaya") gets spelled out as English. `HINGLISH_SCRIPT=roman` switches Hinglish to Roman
script if the voice spike shows the mixed form reads badly.
"""

from __future__ import annotations

import os

HINGLISH_SCRIPT = os.getenv("HINGLISH_SCRIPT", "mixed")  # "mixed" | "roman"

PHRASES: dict[str, dict] = {
    "en": {
        "pause_ack": "Sure, go ahead, I'm listening.",
        "apology": "Sorry, I lost my train of thought there. Could you say that again?",
        "opening": (
            "Hey {name}! Jiya here. Got your briefing ready — {count} {stories}, about "
            "{minutes} {minute_word}. Jump in anytime if something's confusing, yeah?"
        ),
        "story_one": "story",
        "story_many": "stories",
        "minute_one": "minute",
        "minute_many": "minutes",
        "opening_quiet": "Hey {name}! Jiya here. Nothing major worth your time today.",
        "quiet_script": (
            "Honestly, nothing significant enough happened in the areas you follow to justify a "
            "full briefing. No filler, no stretching — I'll keep watching. Take care!"
        ),
        "first": "First up.",
        "middle": [
            "Next one.",
            "Moving on.",
            "Okay, here's another.",
            "Then there's this.",
        ],
        "last": "And finally.",
        "update": "Quick update on one we covered earlier.",
        "closing": (
            "Alright, that's the rundown! I'm still here though — got questions, want me to "
            "explain something again, or just wanna talk through any of this? Fire away."
        ),
        "goodbye": "Cool, I'll let you go, {name}. Catch you tomorrow, same time. Take care!",
        "more": "What else is on your mind?",
        "goodbye_words": [
            "bye",
            "goodbye",
            "that's all",
            "thats all",
            "hang up",
            "thanks jiya",
        ],
        "qa_rules": (
            "Reply in warm, casual Indian English. Short sentences — you are speaking, not writing."
        ),
    },
    "hinglish": {
        "pause_ack": "ठीक है, बोलिए, मैं सुन रही हूँ।",
        "apology": "सॉरी, मैं बात पकड़ नहीं पाई। क्या आप दोबारा बोल सकते हैं?",
        "opening": (
            "हे {name}! मैं Jiya बोल रही हूँ। आपकी briefing ready है — {count} {stories}, करीब "
            "{minutes} मिनट की। कुछ भी confusing लगे तो बीच में रोक देना, ठीक है?"
        ),
        "story_one": "story",
        "story_many": "stories",
        "minute_one": "मिनट",
        "minute_many": "मिनट",
        "opening_quiet": "हे {name}! Jiya here। आज आपके काम की कोई बड़ी खबर नहीं है।",
        "quiet_script": (
            "सच बोलूँ तो आज जिन topics को आप follow करते हैं, उनमें ऐसा कुछ बड़ा नहीं हुआ कि पूरी "
            "briefing बनती। फालतू खींचना नहीं चाहती — मैं नज़र रखती हूँ। Take care!"
        ),
        "first": "सबसे पहले।",
        "middle": ["अगली खबर।", "चलो आगे बढ़ते हैं।", "अब ये सुनो।", "एक और है।"],
        "last": "और आखिर में।",
        "update": "जो हमने पहले cover की थी, उस पर एक quick update।",
        "closing": (
            "तो ये थी आज की briefing! मैं अभी भी यहीं हूँ — कुछ पूछना है, कुछ दोबारा समझाना है, "
            "या बस इस पर बात करनी है? बोलो।"
        ),
        "goodbye": "ठीक है {name}, मैं आपको जाने देती हूँ। कल फिर मिलते हैं, same time पर। Take care!",
        "more": "और कुछ पूछना है?",
        "goodbye_words": [
            "bye",
            "goodbye",
            "बाय",
            "अलविदा",
            "बस इतना ही",
            "बस इतना",
            "फोन रखो",
            "रखती हूँ",
            "that's all",
            "thanks jiya",
            "थैंक्स जिया",
            "शुक्रिया जिया",
        ],
        "qa_rules": (
            "Reply in natural Hinglish like a friend on a call. SCRIPT RULE (a voice engine reads "
            "this): every Hindi word in Devanagari script, every English word, number and name in "
            "Latin script, mixed freely. Never write Hindi words in Roman letters. Example: "
            "'Sensex इसलिए गिरा क्योंकि FIIs ने shares बेचे और US bond yields बढ़ गईं। इसका असर आपके "
            "SIP पर थोड़ा दिख सकता है।' Short sentences. Never use formal shuddh Hindi. You are "
            "female: use feminine verb forms for yourself."
        ),
    },
    "hinglish_roman": {
        "pause_ack": "Theek hai, boliye, main sun rahi hoon.",
        "apology": "Sorry, main baat pakad nahi paayi. Kya aap dobara bol sakte hain?",
        "opening": (
            "Hey {name}! Jiya bol rahi hoon. Aapki briefing ready hai — {count} {stories}, "
            "lagbhag {minutes} minute ki. Kuch bhi confusing lage to beech mein rok dena, theek hai?"
        ),
        "story_one": "story",
        "story_many": "stories",
        "minute_one": "minute",
        "minute_many": "minute",
        "opening_quiet": "Hey {name}! Jiya here. Aaj aapke kaam ki koi badi khabar nahi hai.",
        "quiet_script": (
            "Sach bolun to aaj jin topics ko aap follow karte ho, unmein kuch bada nahi hua. "
            "Faltu kheenchna nahi chahti — main nazar rakhti hoon. Take care!"
        ),
        "first": "Sabse pehle.",
        "middle": [
            "Agli khabar.",
            "Chalo aage badhte hain.",
            "Ab ye suno.",
            "Ek aur hai.",
        ],
        "last": "Aur aakhir mein.",
        "update": "Jo humne pehle cover ki thi, uspe ek quick update.",
        "closing": (
            "Toh ye thi aaj ki briefing! Main abhi bhi yahin hoon — kuch poochna hai, kuch dobara "
            "samjhana hai, ya bas baat karni hai? Bolo."
        ),
        "goodbye": "Theek hai {name}, main aapko jaane deti hoon. Kal phir milte hain, same time par. Take care!",
        "more": "Aur kuch poochna hai?",
        "goodbye_words": [
            "bye",
            "goodbye",
            "alvida",
            "bas itna hi",
            "phone rakho",
            "that's all",
            "thanks jiya",
        ],
        "qa_rules": (
            "Reply in natural Roman-script Hinglish like a friend on a call "
            "('Aaj Sensex 500 points gir gaya'). Short sentences. You are female: use feminine "
            "verb forms for yourself."
        ),
    },
    "hi": {
        "pause_ack": "ठीक है, कहिए, मैं सुन रही हूँ।",
        "apology": "क्षमा कीजिए, मैं बात समझ नहीं पाई। क्या आप दोबारा कह सकते हैं?",
        "opening": (
            "नमस्ते {name}! मैं Jiya बोल रही हूँ। आपकी briefing तैयार है — {count} {stories}, "
            "लगभग {minutes} मिनट। कुछ भी समझ न आए तो बीच में टोक दीजिएगा।"
        ),
        "story_one": "खबर",
        "story_many": "खबरें",
        "minute_one": "मिनट",
        "minute_many": "मिनट",
        "opening_quiet": "नमस्ते {name}! मैं Jiya बोल रही हूँ। आज आपके काम की कोई बड़ी खबर नहीं है।",
        "quiet_script": (
            "सच कहूँ तो आज आपकी पसंद के विषयों में ऐसा कुछ बड़ा नहीं हुआ कि पूरी briefing बनती। "
            "मैं नज़र बनाए रखूँगी। अपना ख़याल रखिए!"
        ),
        "first": "सबसे पहले।",
        "middle": ["अगली खबर।", "आगे बढ़ते हैं।", "अब ये देखिए।", "एक और खबर।"],
        "last": "और आख़िर में।",
        "update": "जिस खबर पर हमने पहले बात की थी, उस पर एक छोटा सा update।",
        "closing": (
            "तो ये थी आज की briefing। मैं अभी भी यहीं हूँ — कुछ पूछना हो, कुछ दोबारा समझाना हो, "
            "तो बेझिझक पूछिए।"
        ),
        "goodbye": "ठीक है {name}, मैं आपको जाने देती हूँ। कल इसी समय फिर मिलेंगे। अपना ख़याल रखिए!",
        "more": "और कुछ जानना है?",
        "goodbye_words": [
            "बाय",
            "अलविदा",
            "बस इतना ही",
            "बस इतना",
            "फोन रखिए",
            "फोन रखो",
            "bye",
            "goodbye",
            "धन्यवाद जिया",
            "शुक्रिया जिया",
        ],
        "qa_rules": (
            "हिंदी में बोलिए, जैसे कोई समझदार दोस्त फोन पर बात करता है — आसान शब्द, छोटे वाक्य। "
            "अंग्रेज़ी नाम और तकनीकी शब्द Latin script में रख सकते हैं। आप महिला हैं: अपने लिए "
            "स्त्रीलिंग क्रियाएँ इस्तेमाल करें।"
        ),
    },
}

REQUIRED_KEYS = frozenset(PHRASES["en"])


def phrases_for(language: str) -> dict:
    """Phrase table for a language code; unknown codes fall back to English."""
    if language == "hinglish" and HINGLISH_SCRIPT == "roman":
        return PHRASES["hinglish_roman"]
    return PHRASES.get(language, PHRASES["en"])
