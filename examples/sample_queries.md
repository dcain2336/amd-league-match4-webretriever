# Sample queries

Try these to see the agent's range. All return an answer, citations,
a confidence score — or an honest refusal when nothing verifiable is found.

## Fact / definition
```
python -m webretriever "What is retrieval-augmented generation?"
```

## Price lookup
```
python -m webretriever "What is the current price of an AMD Ryzen 9 9950X?"
```

## Contact info
```
python -m webretriever "What is the phone number for the Camp Lejeune main gate visitor center?"
```

## Hours
```
python -m webretriever "What are the Saturday hours for the Jacksonville NC DMV?"
```

## Spec lookup
```
python -m webretriever "What is the VRAM on an AMD Radeon RX 9070 XT?"
```

## Date
```
python -m webretriever "When does AMD AI League Match 4 end?"
```

## Unverifiable (expect a refusal)
```
python -m webretriever "What is the exact number of grains of sand on Wrightsville Beach?"
```

## Machine-readable output
```
python -m webretriever --json "What is the price of a Raspberry Pi 5 8GB?" > answer.json
```
