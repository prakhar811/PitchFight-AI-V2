"""Versioned prompt resource files, loaded by app.ai.prompt_loader.

shared/      base judge rules + safety/instruction-priority rules
personas/    one file per {persona_type}_v{n}.md (WHAT a judge cares about)
difficulty/  one file per difficulty (HOW HARD the judge pushes)
tasks/       one file per PromptTask (WHAT the model does this turn)

No Python logic lives here — just Markdown text. See app/ai/prompt_builder.py.
"""
