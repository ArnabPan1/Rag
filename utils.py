import re

def parse_reasoning_and_output(assistant_resposne):
    response = assistant_resposne

    reasoning = re.search(r"Reasoning:\s*(.*?)(?:\n\nAnswer:|$)", response, re.DOTALL)
    answer = re.search(r"Answer:\s*(.*)", response, re.DOTALL)

    reasoning_text = reasoning.group(1).strip() if reasoning else None
    answer_text = answer.group(1).strip() if answer else None
    return reasoning_text, answer_text
