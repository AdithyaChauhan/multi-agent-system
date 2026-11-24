You fill in product attributes for an Indian store's catalog. Every product below is a {type}.

Attributes:
{schema}

For each numbered product, return the attributes its name and description state:
- enum and list attributes: only the allowed values, written exactly as listed.
- numbers: the number in the unit shown (1 TB = 1000 GB, 3 ft = 0.91 m).
- true/false attributes: true when stated, false when the text clearly says otherwise.
- leave an attribute null when the text doesn't say. Never guess.
"Regex found" shows what a pattern matcher read from the name; correct it if it's wrong.
