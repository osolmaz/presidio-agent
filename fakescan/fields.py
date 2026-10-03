"""Label which text lines hold personal data or document numbers."""
import json

from . import vl

FIELDS = ["person_name", "street", "postal_city", "email", "phone", "customer_number", "document_number",
          "date", "card_number", "iban", "terminal_id", "none"]


def label_lines(lines):
    """Return a field label for every line, in order. The vendor's own details are 'none'."""
    listing = "\n".join(f"{i}: {ln['text']}" for i, ln in enumerate(lines))
    prompt = (
        "These are the text lines of a scanned German invoice or receipt, numbered. Label every line that holds "
        "data about the customer or the transaction that should change in a new synthetic copy. Use exactly one of: "
        + ", ".join(FIELDS) + ". The shop or vendor's own name, address, phone, tax IDs, and bank details are "
        "'none'. Labels such as 'Datum:' alone are 'none'. Answer with only a JSON object that maps the line number "
        'to its label, for example {"3": "person_name", "4": "street"}. Leave out lines that are none.\n\n' + listing)
    answer = vl.parse_json(vl.chat([{"type": "text", "text": prompt}], max_tokens=1024))
    labels = ["none"] * len(lines)
    for k, v in answer.items():
        i = int(k)
        if 0 <= i < len(lines) and v in FIELDS:
            labels[i] = v
    return labels


if __name__ == "__main__":
    import sys
    lines = json.load(open(sys.argv[1]))
    print(json.dumps(label_lines(lines), indent=1))
