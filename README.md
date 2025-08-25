# MTG-Card-Downloader
AI generated script to download MTG cards from a list of card names

## Translate card names

```
scryfall_translate.py --input cards.txt --out translation.csv --lang es
```

## Download cards

```
scryfall_downloader.py --input cards.txt --out Deck --size normal --lang es
```

> Deck is the directory where the cardes will be placed.