"""
Held-out routing prompts: 8 per tier, labelled by hand on 2026-11-17.

Unlike LABELLED, these were written and labelled before the classifier was run
on them, and the rules must not be changed to fit them. If a rule change moves
the score here, that is the honest measure of it; a prompt is never edited or
relabelled to make a number go up. Keep the misses visible.

Labels, the same standard as LABELLED:
  simple  - a fact, a definition, a short lookup or rewrite
  medium  - an explanation, comparison or piece of writing
  complex - code, a system design, a proof, or a multi-step technical task
"""

HELD_OUT: list[tuple[str, str]] = [
    ("simple", "What is the boiling point of water at sea level?"),
    ("simple", "Who wrote Pride and Prejudice?"),
    ("simple", "Convert 5 kilometres to miles"),
    ("simple", "What does HTTP stand for?"),
    ("simple", "Give me a synonym for 'happy'"),
    ("simple", "When was the first iPhone released?"),
    ("simple", "How many bytes are in a kilobyte?"),
    ("simple", "Fix the spelling in this sentence: 'I recieved the pakage yesterday.'"),
    ("medium", "Explain how a vaccine trains the immune system"),
    ("medium", "What are the main differences between SQL and NoSQL databases, and when would you pick each?"),
    ("medium", "Write a polite email asking my manager for a day off next Friday"),
    ("medium", "Describe the causes of the 2008 financial crisis in a few paragraphs"),
    ("medium", "Compare Python and Go for building a web API"),
    ("medium", "Summarize the plot of Hamlet and explain why Hamlet delays his revenge"),
    ("medium", "Give me the pros and cons of microservices versus a monolith for a team of five"),
    ("medium", "How does a hash map handle collisions?"),
    ("complex", "Implement a thread-safe bounded queue in Java with blocking put and take"),
    ("complex", "Write a Python function that parses a cron expression and returns the next 5 run times, with unit tests"),
    ("complex", "Design a rate limiter for an API gateway that handles 100k requests per second across many nodes, "
                "and explain how you would test it"),
    ("complex", "Prove that the square root of 2 is irrational"),
    ("complex", "This SQL query takes 30 seconds on 10 million rows: SELECT * FROM orders WHERE "
                "LOWER(email) = 'a@b.com' ORDER BY created_at DESC. Find the problem and rewrite it with the right index."),
    ("complex", "Build a React hook that debounces a search input and cancels stale fetch requests"),
    ("complex", "Step 1: load a CSV of transactions. Step 2: flag duplicates within 5 minutes. "
                "Step 3: write the flagged rows to a new file. Give me the Python code."),
    ("complex", "Optimize this function, which is O(n^2):\n```python\ndef has_pair(xs, target):\n"
                "    return any(a + b == target for i, a in enumerate(xs) for b in xs[i+1:])\n```"),
]
