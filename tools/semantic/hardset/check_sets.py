"""Do the paraphrases and translations really share no content word with their target?

The English paraphrases are the part of the hard set that claims to be free of the
target's own words, so the claim is checked rather than trusted. Words are split the
way Leteo's `prompt_terms` splits (alphanumeric or `_`, three characters or more,
lowercased) and function words are ignored. Two words are shared when equal after
folding accents, or when both have five characters or more and begin with the same five
(`connection`, `connections`).

The English paraphrases are checked against the English function words alone: the
union of thirteen languages' would swallow English content words that are function
words elsewhere (`care`, `door`, `plus`, `sin`, `come`, `die`, `war`), and a paraphrase
could share one with its target unseen. The check of the translated memories, which is
informational, uses the union, because there a word of any of the languages is a
function word.

Before anything else it checks that the data files are the ones `checksums.json`
records. The data is 237 KB of generated questions that no reader reviews line by line,
so what stands in for the review is that it is the set that was measured. The
decompressed hash is the claim: a file that decompresses to anything else, that is not
gzip, that is missing, or that nobody recorded fails. The stored hash is the weaker
one, since another zlib may write other valid bytes for the same questions, so a file
whose stored bytes differ and whose content does not is reported and does not fail.

Exit codes: 0 when the set holds, 1 for a violation of the invariant, 2 for anything
that stopped the check from being made -- changed data, or a failure to read it.

usage: check_sets.py
"""

import gzip
import hashlib
import json
import os
import sys
import unicodedata
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

STOP_ENGLISH = set(
    """the and for with that this from into over under when what which who whom whose why how where was were are is be been being
has have had does did not but all any can could should would will may might must our ours their them they then than there these those
its it's you your yours we us he she his her him one two three also only just very more most some such each other about after before
again against because between both down during few further here off once out own same too until while above below through very per via""".split()
)

STOP_OTHERS = set(
    """el la los las un una unos unas de del al y o u que en por para con sin sobre entre se su sus lo le les es son fue era muy mas más como
cuando donde qué por porqué porque este esta estos estas ese esa eso nos nuestro nuestra no si sí ya hay ha han
els les una uns del dels amb per que com quan on aquest aquesta això són més
der die das den dem des ein eine einen einem einer und oder mit für von bei aus nach ist sind war wurde wird nicht auch wie wenn wir unser
le les des une du et ou avec pour par dans sur sont est pas plus que qui quand comment pourquoi nous notre
il lo gli una uno del della dei delle con per che non come quando perché sono noi nostro
het een van met voor door bij uit naar niet ook hoe wanneer waarom wij onze zijn werd
na nie się jest są jak dla przez kiedy dlaczego czy nasz
um uma uns umas com por para que não como quando porque são nós nosso foi
și cu pentru din care nu este sunt cum când nostru
och med för att som inte hur när varför vår vara blev
eta ez da dira bat zer nola zergatik noiz gure
o a os as un unha unhas do da dos das e ou que en por para con sen sobre entre se seu súa seus súas como cando onde porque este esta estes
estas ese esa iso non si xa hai foi era moi máis nos noso nosa""".split()
)

STOP_ALL = STOP_ENGLISH | STOP_OTHERS


def words(text: str, stop: set[str]) -> set[str]:
    found, current = [], []
    for char in text + " ":
        if char.isalnum() or char == "_":
            current.append(char)
        elif current:
            found.append("".join(current))
            current = []
    return {w.lower() for w in found if len(w) >= 3 and w.lower() not in stop}


def fold(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))


def same_word(a: str, b: str) -> bool:
    """Equal, or long enough to share a five-letter start."""
    if a == b:
        return True
    return len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5]


def shared(query: str, document: str, stop: set[str]) -> set[str]:
    asked = {fold(w) for w in words(query, stop)}
    held = {fold(w) for w in words(document, stop)}
    return {a for a in asked for b in held if same_word(a, b)}


def read(name: str):
    """The JSON of one data file, which is stored as deterministic gzip."""
    with gzip.open(os.path.join(HERE, "data", name + ".gz"), "rb") as handle:
        return json.load(handle)


def verify_data() -> bool:
    """Every file under data/ is the one recorded, and no other is there.

    False when the check cannot be trusted: a file that is not gzip, that
    decompresses to anything other than what was recorded, that is missing or that
    nobody recorded. A file whose stored bytes differ from the record while its
    content does not is printed and passes; see the module docstring.
    """
    recorded = json.load(open(os.path.join(HERE, "checksums.json")))
    folder = os.path.join(HERE, "data")
    stored, decompressed, ok = {}, {}, True
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or not name.endswith(".json.gz"):
            print(f"data/{name} is not a data file")
            ok = False
            continue
        raw = open(path, "rb").read()
        stored[name] = hashlib.sha256(raw).hexdigest()
        try:
            decompressed[name[:-3]] = hashlib.sha256(gzip.decompress(raw)).hexdigest()
        except (OSError, EOFError, zlib.error, ValueError) as error:
            print(f"data/{name} is not readable gzip: {error}")
            ok = False
    for name in sorted(set(recorded["decompressed"]) | set(decompressed)):
        want, got = recorded["decompressed"].get(name), decompressed.get(name)
        if want != got:
            print(f"data/{name} (decompressed): recorded {want}, found {got}")
            ok = False
    for name in sorted(set(recorded["files"]) | set(stored)):
        want, got = recorded["files"].get(name), stored.get(name)
        if want != got and decompressed.get(name[:-3]) == recorded["decompressed"].get(name[:-3]):
            print(f"data/{name}: stored bytes differ from the record, the questions do not (another zlib?)")
    return ok


def main() -> int:
    if not verify_data():
        print("the hard-set data is not the data checksums.json records")
        return 2
    # After the data is known to be the recorded data, not before: the corpus
    # module is the engram-bench one and has nothing to do with whether the
    # files can be trusted.
    sys.path.insert(0, os.path.join(HERE, "..", "..", "engram-bench"))
    import corpus as C

    targets = {t["key"]: t for t in C.TARGETS}
    english = [(q, targets[q["key"]]) for q in read("para_en.json")]
    bad = 0
    for q, target in english:
        hits = shared(q["q"], target["title"] + " " + target["content"], STOP_ENGLISH)
        if hits:
            bad += 1
            print(f"para_en: {q['key']}: {q['q']!r} shares {sorted(hits)}")
    print(f"{len(english)} English paraphrases checked against their English target, {bad} share a content word")

    # The translated stores keep the English paraphrases and replace the memory
    # with its translation. A cognate or a technical term the translator left
    # alone (`permission`/`permiso`, `FOIT`) is a shared word there, and is not
    # a defect of the set: the claim is made of the English store, and these are
    # counted so nobody has to take that on trust.
    cognates = 0
    for lang in "de es eu gl".split():
        translated = {t["key"]: t for t in read(f"mem_{lang}.json")}
        for q, _ in english:
            target = translated[q["key"]]
            if shared(q["q"], target["title"] + " " + target["content"], STOP_ALL):
                cognates += 1
    print(f"{cognates} of {4 * len(english)} paraphrase/translation pairs share a word through a cognate or a kept term (informational)")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 -- 1 is for violations; anything else is "could not check"
        print(f"the check could not be made: {type(error).__name__}: {error}")
        sys.exit(2)
