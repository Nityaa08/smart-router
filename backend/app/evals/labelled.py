"""
Hand-labelled routing prompts: 8 per tier, labels written by hand.

The rules were adjusted with these prompts in view (10 of 24 routed as
labelled before the keyword-scoring change, 23 after), so this is a
regression set, not a held-out measure of the classifier. The one miss is
kept on purpose and reported, not tuned away.
"""

LABELLED: list[tuple[str, str]] = [
    ("simple", "What is 2+2?"),
    ("simple", "What is the capital of France? Who is its president? When was the Eiffel Tower built?"),
    ("simple", "What is DNS? How many root servers are there?"),
    ("simple", "Define latency and list the main causes"),
    ("simple", "Who is Alan Turing and when was he born?"),
    ("simple", "Translate 'good morning' to French and Spanish"),
    ("simple", "Summarize this in one sentence: the meeting moved to Thursday because the venue was booked."),
    ("simple", "Name the planets in the solar system"),
    ("medium", "Explain the difference between TCP and UDP and when to use each"),
    ("medium", "Compare REST and GraphQL for a mobile app backend and explain the trade-offs"),
    ("medium", "How does garbage collection work in Java? Explain with an example."),
    ("medium", "Write a cover letter for a junior data analyst role and describe why I am a good fit"),
    ("medium", "Explain how neural networks learn, focusing on gradient optimization techniques"),
    ("medium", "Why does my React component render twice? Explain the common causes."),
    ("medium", "Describe how HTTPS works and compare it with plain HTTP"),
    ("medium", "Analyze the pros and cons of remote work for a small startup"),
    ("complex", "Implement a recursive algorithm to find all permutations of a list in Python. "
                "First analyze the complexity, then write the code with tests."),
    ("complex", "Design a distributed caching system, then implement the consistent hashing algorithm "
                "and analyze its Big-O complexity"),
    ("complex", "Implement quicksort in Python with complexity analysis"),
    ("complex", "Prove that the halting problem is undecidable"),
    ("complex", "Debug this function and refactor it for speed:\n```python\ndef f(xs):\n"
                "    return [x for x in xs if xs.count(x) > 1]\n```"),
    ("complex", "Design a system for real-time fraud detection: first outline the architecture, "
                "then implement the scoring algorithm"),
    ("complex", "Derive the time complexity of merge sort from its recurrence, then optimize it for nearly sorted input"),
    ("complex", "Implement an LRU cache in Python with O(1) get and put"),
]

# Prompts the current rules route differently from their label (index into LABELLED).
KNOWN_MISSES = {15: "one medium keyword scores 1, which is simple"}
