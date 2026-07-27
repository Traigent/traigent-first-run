"""Minimal walkthrough agent. Knobs are read from config_space.json by the
onboarding; this stub just shows where each knob plugs into the call path."""
def run(input_text, config):
    model = config.get("model", "gpt-4o-mini")
    # prompt_style / output_format / fewshot_k / retrieval / reasoning / routing
    # would shape the real provider call. Fixture stub echoes the wiring only.
    return {"model": model, "config": config, "input": input_text}
