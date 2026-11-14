"""All user-facing text, in English and Amharic.

Rules return a message *type* and its values; `render()` turns that into text
in the user's language, falling back to English. The app receives the type and
values too, so it can build its own UI.

NOTE: the Amharic strings are a first draft and need review by a native
speaker before the demo.
"""

TEXTS: dict[str, dict[str, str]] = {
    # --- Notifications (rules) -------------------------------------------
    "trip_routed": {
        "en": "🗺 Route ready: about {minutes} min, {km} km to {dest}.",
        "am": "🗺 መንገዱ ዝግጁ ነው፦ ወደ {dest} {km} ኪ.ሜ፣ በግምት {minutes} ደቂቃ።",
    },
    "tracking_started": {
        "en": "✅ Got your location. I'll tell you when something matters — you can put your phone away.",
        "am": "✅ አካባቢዎን አግኝቻለሁ። አስፈላጊ ነገር ሲኖር እነግርዎታለሁ — ስልክዎን ማስቀመጥ ይችላሉ።",
    },
    "new_place": {
        "en": "📍 You are passing {place}.",
        "am": "📍 አሁን {place} አጠገብ እያለፉ ነው።",
    },
    "new_street": {
        "en": "🛣 You are now on {street}.",
        "am": "🛣 አሁን {street} ላይ ነዎት።",
    },
    "time_left": {
        "en": "⏱ About {minutes} minutes to your destination.",
        "am": "⏱ ወደ መድረሻዎ በግምት {minutes} ደቂቃ ቀርቷል።",
    },
    "still_here": {
        "en": "🚌 You are still on {street}. About {minutes} min left.",
        "am": "🚌 አሁንም {street} ላይ ነዎት። በግምት {minutes} ደቂቃ ቀርቷል።",
    },
    "still_here_nostreet": {
        "en": "🚌 Still on the way. About {minutes} min left.",
        "am": "🚌 አሁንም በጉዞ ላይ ነዎት። በግምት {minutes} ደቂቃ ቀርቷል።",
    },
    "getting_close": {
        "en": "🔔 Your destination is close. Get ready.",
        "am": "🔔 መድረሻዎ ተቃርቧል። ይዘጋጁ።",
    },
    "next": {
        "en": "🔔 Your destination is next. Get ready to get off.",
        "am": "🔔 መድረሻዎ ቀጥሎ ነው። ለመውረድ ይዘጋጁ።",
    },
    "arrived": {
        "en": "🎉 You have arrived at {dest}.",
        "am": "🎉 {dest} ደርሰዋል።",
    },
    "location_lost": {
        "en": "⚠️ I can't see your location. Please share live location again: 📎 → Location → Share My Live Location.",
        "am": "⚠️ አካባቢዎን ማየት አልቻልኩም። እባክዎ የቀጥታ አካባቢዎን እንደገና ያጋሩ፦ 📎 → Location → Share My Live Location።",
    },
    "tracking_resumed": {
        "en": "✅ I can see your location again.",
        "am": "✅ አካባቢዎን እንደገና አግኝቻለሁ።",
    },
    "trip_ended": {
        "en": "🏁 Trip ended. Safe travels!",
        "am": "🏁 ጉዞው ተጠናቋል። መልካም ጉዞ!",
    },
    "trip_ended_timeout": {
        "en": "🏁 I ended the trip because I haven't seen your location for 10 minutes.",
        "am": "🏁 ለ10 ደቂቃ አካባቢዎን ስላላየሁ ጉዞውን አቁሜዋለሁ።",
    },
    "food_offer": {
        "en": "☕ There are {count} cafés and restaurants within 500 m. Want to see them?",
        "am": "☕ በ500 ሜትር ውስጥ {count} ካፌዎችና ምግብ ቤቶች አሉ። ማየት ይፈልጋሉ?",
    },
    # --- Replies to buttons ---------------------------------------------
    "where_am_i": {
        "en": "📍 You are on {street}, near {landmark}.",
        "am": "📍 አሁን {street} ላይ ነዎት፣ {landmark} አጠገብ።",
    },
    "where_am_i_street": {
        "en": "📍 You are on {street}.",
        "am": "📍 አሁን {street} ላይ ነዎት።",
    },
    "where_am_i_landmark": {
        "en": "📍 You are near {landmark}.",
        "am": "📍 አሁን {landmark} አጠገብ ነዎት።",
    },
    "where_am_i_unknown": {
        "en": "📍 I can't name this spot yet, but I'm tracking you.",
        "am": "📍 ይህን ቦታ መሰየም አልቻልኩም፣ ግን እየተከታተልኩዎት ነው።",
    },
    "dest_suffix": {
        "en": " About {km} km to {dest}.",
        "am": " ወደ {dest} {km} ኪ.ሜ ቀርቷል።",
    },
    "time_left_status": {
        "en": "⏱ About {minutes} min and {km} km to {dest}.",
        "am": "⏱ ወደ {dest} በግምት {minutes} ደቂቃ፣ {km} ኪ.ሜ ቀርቷል።",
    },
    "food_list_title": {
        "en": "🍽 Places to eat nearby:",
        "am": "🍽 በአቅራቢያ ያሉ ምግብ ቤቶች፦",
    },
    "food_none": {
        "en": "🍽 I couldn't find restaurants or cafés within 500 m.",
        "am": "🍽 በ500 ሜትር ውስጥ ምግብ ቤት ወይም ካፌ አላገኘሁም።",
    },
    "food_item": {
        "en": "{n}. {name} ({kind}) · {meters} m",
        "am": "{n}. {name} ({kind}) · {meters} ሜ",
    },
    # --- Trip card -----------------------------------------------------
    "card": {
        "en": "🧭 To {dest}\n📏 {km} km left · ⏱ about {minutes} min\n📍 {street}",
        "am": "🧭 ወደ {dest}\n📏 {km} ኪ.ሜ ቀርቷል · ⏱ በግምት {minutes} ደቂቃ\n📍 {street}",
    },
    "card_waiting": {
        "en": "🧭 To {dest}\n⏳ Waiting for your live location…",
        "am": "🧭 ወደ {dest}\n⏳ የቀጥታ አካባቢዎን በመጠበቅ ላይ…",
    },
    "card_done": {
        "en": "🏁 Trip to {dest} finished.",
        "am": "🏁 ወደ {dest} የተደረገው ጉዞ ተጠናቋል።",
    },
    "card_unknown_street": {"en": "…", "am": "…"},
    # --- Bot conversation -----------------------------------------------
    "welcome": {
        "en": "👋 Welcome to Menged! I tell you where you are and when to get off.\nChoose your language:",
        "am": "👋 እንኳን ወደ መንገድ በደህና መጡ! የት እንዳሉ እና መቼ እንደሚወርዱ እነግርዎታለሁ።\nቋንቋ ይምረጡ፦",
    },
    "ready": {
        "en": "All set. 🔊 Voice notes are on (change in /settings).\n\n👉 Where are you going? Type a place name, e.g. <i>Bole Medhanialem</i>.",
        "am": "ዝግጁ ነው። 🔊 የድምፅ መልዕክቶች በርተዋል (/settings ላይ ይቀይሩ)።\n\n👉 ወዴት ይሄዳሉ? የቦታ ስም ይጻፉ፣ ለምሳሌ <i>ቦሌ መድኃኔዓለም</i>።",
    },
    "ask_destination": {
        "en": "👉 Where are you going? Type a place name.",
        "am": "👉 ወዴት ይሄዳሉ? የቦታ ስም ይጻፉ።",
    },
    "searching": {"en": "🔎 Searching…", "am": "🔎 በመፈለግ ላይ…"},
    "pick_destination": {
        "en": "Which one did you mean?",
        "am": "የትኛውን ማለትዎ ነው?",
    },
    "none_of_these": {"en": "❌ None of these", "am": "❌ አንዳቸውም አይደሉም"},
    "not_found": {
        "en": "😕 I couldn't find “{query}”. Try another name or a nearby landmark.",
        "am": "😕 “{query}” አላገኘሁም። ሌላ ስም ወይም በአቅራቢያ ያለ ታዋቂ ቦታ ይሞክሩ።",
    },
    "search_failed": {
        "en": "😕 Map search is slow right now. Please try again in a moment.",
        "am": "😕 የካርታ ፍለጋው አሁን ዘግይቷል። እባክዎ ትንሽ ቆይተው ይሞክሩ።",
    },
    "dest_set_share": {
        "en": (
            "🎯 Destination: <b>{dest}</b>\n\n"
            "Now share your <b>live location</b> so I can guide you:\n"
            "1. Tap 📎 (attach)\n2. Tap <b>Location</b>\n3. Tap <b>Share My Live Location</b>\n"
            "4. Choose <b>8 hours</b> or <b>Until I turn it off</b>"
        ),
        "am": (
            "🎯 መድረሻ፦ <b>{dest}</b>\n\n"
            "እንድመራዎ <b>የቀጥታ አካባቢዎን</b> ያጋሩ፦\n"
            "1. 📎 ይጫኑ\n2. <b>Location</b> ይጫኑ\n3. <b>Share My Live Location</b> ይጫኑ\n"
            "4. <b>8 hours</b> ወይም <b>Until I turn it off</b> ይምረጡ"
        ),
    },
    "routing": {"en": "🗺 Planning your route…", "am": "🗺 መንገድዎን በማቀድ ላይ…"},
    "route_failed": {
        "en": "😕 I couldn't plan a route right now. I'll keep tracking and still tell you when you're close.",
        "am": "😕 አሁን መንገድ ማቀድ አልቻልኩም። መከታተሌን እቀጥላለሁ፤ ሲቃረቡ እነግርዎታለሁ።",
    },
    "need_live": {
        "en": "That was a one-time location. For guidance I need your <b>live</b> location: 📎 → Location → <b>Share My Live Location</b>.",
        "am": "ይህ የአንድ ጊዜ አካባቢ ነው። ለመምራት <b>የቀጥታ</b> አካባቢ ያስፈልገኛል፦ 📎 → Location → <b>Share My Live Location</b>።",
    },
    "need_destination_first": {
        "en": "📌 Got your location. Where are you going? Type a place name.",
        "am": "📌 አካባቢዎን አግኝቻለሁ። ወዴት ይሄዳሉ? የቦታ ስም ይጻፉ።",
    },
    "already_on_trip": {
        "en": "You're already on a trip to <b>{dest}</b>. Tap ⏹ Stop trip to start a new one.",
        "am": "ወደ <b>{dest}</b> ጉዞ ላይ ነዎት። አዲስ ለመጀመር ⏹ ጉዞ አቁም ይጫኑ።",
    },
    "no_trip": {
        "en": "You have no active trip. Type where you are going, or tap 📌 Send my location.",
        "am": "ንቁ ጉዞ የለዎትም። ወዴት እንደሚሄዱ ይጻፉ፣ ወይም 📌 አካባቢዬን ላክ ይጫኑ።",
    },
    "no_position": {
        "en": "I don't have your position yet. Share your live location, or tap 📌 Send my location.",
        "am": "አካባቢዎን ገና አላገኘሁም። የቀጥታ አካባቢዎን ያጋሩ ወይም 📌 አካባቢዬን ላክ ይጫኑ።",
    },
    "offer_later": {"en": "👍 I'll ask again later.", "am": "👍 በኋላ እጠይቃለሁ።"},
    "offer_off": {"en": "👍 No more food suggestions on this trip.", "am": "👍 በዚህ ጉዞ ተጨማሪ የምግብ ጥቆማ የለም።"},
    "settings_title": {
        "en": "⚙️ Settings\nLanguage: {language}\nVoice notes: {voice}\nAlerts: {level}",
        "am": "⚙️ ቅንብሮች\nቋንቋ፦ {language}\nየድምፅ መልዕክት፦ {voice}\nማሳወቂያ፦ {level}",
    },
    "on": {"en": "on", "am": "በርቷል"},
    "off": {"en": "off", "am": "ጠፍቷል"},
    "level_quiet": {"en": "quiet (important only)", "am": "ጸጥ (አስፈላጊ ብቻ)"},
    "level_normal": {"en": "normal", "am": "መደበኛ"},
    "level_chatty": {"en": "chatty (everything)", "am": "ብዙ (ሁሉንም)"},
    "simulate_start": {
        "en": "🎬 Demo: replaying a recorded trip from {start} to {dest}…",
        "am": "🎬 ማሳያ፦ ከ{start} ወደ {dest} የተቀዳ ጉዞ በመድገም ላይ…",
    },
    "simulate_denied": {"en": "This command is for the demo team.", "am": "ይህ ትዕዛዝ ለማሳያ ቡድኑ ብቻ ነው።"},
    "simulate_missing": {
        "en": "No demo trip saved. Run scripts/record_demo.py first.",
        "am": "የተቀመጠ የማሳያ ጉዞ የለም።",
    },
    "help": {
        "en": (
            "How to use Menged:\n"
            "1. Type where you are going.\n"
            "2. Pick the right place.\n"
            "3. Share your live location (📎 → Location → Share My Live Location).\n"
            "I'll tell you what you pass and when to get off.\n\n"
            "/trip – new trip · /settings – language, voice, alerts"
        ),
        "am": (
            "መንገድን እንዴት እንደሚጠቀሙ፦\n"
            "1. ወዴት እንደሚሄዱ ይጻፉ።\n"
            "2. ትክክለኛውን ቦታ ይምረጡ።\n"
            "3. የቀጥታ አካባቢዎን ያጋሩ (📎 → Location → Share My Live Location)።\n"
            "የሚያልፉትን እና መቼ እንደሚወርዱ እነግርዎታለሁ።\n\n"
            "/trip – አዲስ ጉዞ · /settings – ቋንቋ፣ ድምፅ፣ ማሳወቂያ"
        ),
    },
    # --- Buttons ---------------------------------------------------------
    "btn_where": {"en": "📍 Where am I?", "am": "📍 የት ነኝ?"},
    "btn_time": {"en": "⏱ Time left", "am": "⏱ ቀሪ ጊዜ"},
    "btn_nearby": {"en": "🍽 Nearby restaurants", "am": "🍽 አቅራቢያ ምግብ ቤቶች"},
    "btn_stop": {"en": "⏹ Stop trip", "am": "⏹ ጉዞ አቁም"},
    "btn_send_location": {"en": "📌 Send my location", "am": "📌 አካባቢዬን ላክ"},
    "btn_show": {"en": "👀 Show", "am": "👀 አሳይ"},
    "btn_later": {"en": "⏰ Not now", "am": "⏰ አሁን አይደለም"},
    "btn_no_more": {"en": "🚫 Don't ask this trip", "am": "🚫 በዚህ ጉዞ አይጠይቁ"},
    "btn_language": {"en": "🌐 Language", "am": "🌐 ቋንቋ"},
    "btn_voice": {"en": "🔊 Voice: {state}", "am": "🔊 ድምፅ፦ {state}"},
    "btn_level": {"en": "🔔 Alerts: {level}", "am": "🔔 ማሳወቂያ፦ {level}"},
    # --- Bot command descriptions ---------------------------------------
    "cmd_start": {"en": "Start / choose language", "am": "ጀምር / ቋንቋ ምረጥ"},
    "cmd_trip": {"en": "Start a new trip", "am": "አዲስ ጉዞ ጀምር"},
    "cmd_settings": {"en": "Language, voice, alerts", "am": "ቋንቋ፣ ድምፅ፣ ማሳወቂያ"},
    "cmd_help": {"en": "How it works", "am": "እንዴት እንደሚሰራ"},
}

LANGUAGES = {"en": "English", "am": "አማርኛ"}


def render(key: str, lang: str = "en", **params: object) -> str:
    variants = TEXTS[key]
    template = variants.get(lang) or variants["en"]
    return template.format(**params)


def all_variants(key: str) -> set[str]:
    """Every language's text for a key (used to match button presses)."""
    return set(TEXTS[key].values())


def fmt_km(meters: float | None) -> str:
    if meters is None:
        return "?"
    km = meters / 1000
    return f"{km:.1f}" if km < 10 else f"{km:.0f}"


def fmt_minutes(seconds: float | None) -> int:
    if seconds is None:
        return 0
    return max(1, round(seconds / 60))
