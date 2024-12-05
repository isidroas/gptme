import random

# Name generation lists
actions = [
    "running",
    "jumping",
    "walking",
    "skipping",
    "hopping",
    "flying",
    "swimming",
    "crawling",
    "sneaking",
    "sprinting",
    "sneaking",
    "dancing",
    "singing",
    "laughing",
]
adjectives = [
    "funny",
    "happy",
    "sad",
    "angry",
    "silly",
    "crazy",
    "sneaky",
    "sleepy",
    "hungry",
    # colors
    "red",
    "blue",
    "green",
    "pink",
    "purple",
    "yellow",
    "orange",
]
nouns = [
    "cat",
    "dog",
    "rat",
    "mouse",
    "fish",
    "elephant",
    "dinosaur",
    # birds
    "bird",
    "pelican",
    # fictional
    "dragon",
    "unicorn",
    "mermaid",
    "monster",
    "alien",
    "robot",
    # sea creatures
    "whale",
    "shark",
    "walrus",
    "octopus",
    "squid",
    "jellyfish",
    "starfish",
    "penguin",
    "seal",
]


def generate_name():
    action = random.choice(actions)
    adjective = random.choice(adjectives)
    noun = random.choice(nouns)
    return f"{action}-{adjective}-{noun}"


def is_generated_name(name: str) -> bool:
    """if name is a name generated by generate_name"""
    all_words = actions + adjectives + nouns
    return name.count("-") == 2 and all(word in all_words for word in name.split("-"))
