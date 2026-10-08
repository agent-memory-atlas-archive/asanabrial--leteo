"""Checks that an inflection set can only be answered by a stemmer.

For every query word that no memory of the set spells the same way, the nearest
word the store holds must be further away than the typo stage's budget, or the
typo stage could answer the query and the set would not be measuring the
stemmer. Reads `typo_budget`'s rule from `src/store/search.rs` rather than
restating it, so the two cannot drift.

Needs the `snowballstemmer` package, only to say which words a stemmer would
fold together; the measurement itself never uses it.
"""
import os, re, sys, unicodedata

from inflection_sets import SETS

SEARCH_RS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "store", "search.rs")
ALGORITHM = {"es": "spanish", "pt": "portuguese", "fr": "french", "de": "german",
             "it": "italian", "ro": "romanian", "nl": "dutch", "sv": "swedish",
             "ca": "catalan", "eu": "basque", "pl": "polish"}


def budget(chars):
    source = open(SEARCH_RS, encoding="utf-8").read()
    short = int(re.search(r"TYPO_SHORT_DISTANCE: usize = (\d+)", source).group(1))
    long = int(re.search(r"TYPO_LONG_DISTANCE: usize = (\d+)", source).group(1))
    limit = int(re.search(r"TYPO_SHORT_TERM_CHARS: usize = (\d+)", source).group(1))
    return short if chars <= limit else long


def fold(word):
    return "".join(c for c in unicodedata.normalize("NFD", word.lower()) if not unicodedata.combining(c))


def words(text):
    return [w for w in re.split(r"[^\w]+", text) if w]


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        new = [i]
        for j, cb in enumerate(b, 1):
            new.append(min(row[j] + 1, new[j - 1] + 1, row[j - 1] + (ca != cb)))
        row = new
    return row[-1]


def check(code, spec, stemmer):
    problems = []
    texts = {key: f"{title} {content}" for key, (title, content) in spec["memories"].items()}
    vocabulary = {fold(w) for text in texts.values() for w in words(text)}
    stems = {key: {stemmer.stemWord(w.lower()) for w in words(text)} for key, text in texts.items()}
    for query, target in spec["queries"]:
        changed = 0
        for word in words(query):
            if stemmer.stemWord(word.lower()) not in stems[target]:
                problems.append(f"{code} {query!r}: {word!r} has no stem in {target}")
            if fold(word) in vocabulary:
                continue
            changed += 1
            nearest, held = min((distance(fold(word), known), known) for known in vocabulary)
            if nearest <= budget(len(word)):
                problems.append(f"{code} {query!r}: {word!r} is {nearest} edits from {held!r}, within the typo budget")
        if not changed:
            problems.append(f"{code} {query!r}: every word is spelled as a memory spells it")
    return problems


def main():
    import snowballstemmer
    problems = []
    for code, spec in SETS.items():
        problems += check(code, spec, snowballstemmer.stemmer(ALGORITHM[code]))
    for line in problems:
        print(line)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
