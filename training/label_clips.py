"""Labels the voice samples the plugin collected on the Pi (wakeword_training/auto/<model>/*.wav +
.json) and sorts them into training data - run on the training PC after fetching them:

    rsync -av pi@rec-pi:/mnt/32recorder/wakeword_training/auto/ ~/wakeword_data/auto/
    pip install faster-whisper
    python training/label_clips.py --samples ~/wakeword_data/auto --out ~/wakeword_data

Per clip, a label someone set on the Pi's review page wins. Everything else is transcribed with
Whisper and compared with the model's phrase (the "wake_word" of wakewords/<model>.json):
- the phrase was said                 -> positiv: copied to <out>/positives_real/<model>/auto_*.wav
- clearly something else (singing,
  talking, another command)           -> negativ: copied to <out>/negatives_auto/<model>/*.wav
- too unclear to decide               -> unklar: only listed at the end, for a manual look
The decision is written into the clip's JSON as "auto_label" (text, score, model used), so a
second run only transcribes new clips.
"""
import argparse
import difflib
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WAKEWORDS = os.path.join(os.path.dirname(HERE), 'wakewords')

POSITIVE_SCORE = 0.8
UNCLEAR_SCORE = 0.55


def normalize(text):
    text = text.lower().replace('tapedeck', 'tape deck').replace('tape-deck', 'tape deck')
    return ' '.join(re.sub(r"[^a-z0-9äöüß' ]+", ' ', text).split())


def phrase_for(model):
    try:
        with open(os.path.join(WAKEWORDS, model + '.json'), encoding='utf-8') as f:
            return normalize(json.load(f).get('wake_word') or '')
    except (OSError, ValueError):
        return normalize(model.replace('_', ' '))


def match_score(phrase, text):
    """Best similarity between the phrase and any stretch of the transcript of about its length."""
    words, target = text.split(), phrase.split()
    if not words or not target:
        return 0.0
    best = 0.0
    for size in range(max(1, len(target) - 1), len(target) + 2):
        for start in range(0, max(1, len(words) - size + 1)):
            window = ' '.join(words[start:start + size])
            best = max(best, difflib.SequenceMatcher(None, phrase, window).ratio())
    return best


def decide(phrase, text, other_phrases):
    score = match_score(phrase, text)
    if score >= POSITIVE_SCORE:
        return 'positiv', score
    if any(match_score(p, text) >= POSITIVE_SCORE for p in other_phrases):
        return 'negativ', score  # another command - a negative for this model
    if score >= UNCLEAR_SCORE or not text:
        return 'unklar', score
    return 'negativ', score


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--samples', required=True, help='Ordner wakeword_training/auto (vom Pi geholt)')
    ap.add_argument('--out', required=True, help='Zielordner für positives_real/ und negatives_auto/')
    ap.add_argument('--whisper-model', default='small.en')
    ap.add_argument('--device', default='auto', help='cuda / cpu / auto')
    ap.add_argument('--retranscribe', action='store_true', help='auch schon automatisch bewertete Clips neu')
    args = ap.parse_args()

    clips = []
    for model in sorted(os.listdir(args.samples)):
        folder = os.path.join(args.samples, model)
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.endswith('.json') and os.path.isfile(os.path.join(folder, name[:-5] + '.wav')):
                    clips.append((model, os.path.join(folder, name)))
    if not clips:
        sys.exit(f'Keine Clips in {args.samples}')

    phrases = {model: phrase_for(model) for model, _ in clips}
    whisper = None
    counts = {}
    unclear = []
    for model, json_path in clips:
        with open(json_path, encoding='utf-8') as f:
            meta = json.load(f)
        wav = json_path[:-5] + '.wav'
        label, how = meta.get('label'), 'Prüfliste'
        if not label:
            auto = meta.get('auto_label')
            if not auto or args.retranscribe:
                if whisper is None:
                    try:
                        from faster_whisper import WhisperModel
                    except ImportError:
                        sys.exit('Bitte zuerst installieren: pip install faster-whisper')
                    whisper = WhisperModel(args.whisper_model, device=args.device)
                segments, _ = whisper.transcribe(wav, language='en', beam_size=5, vad_filter=False)
                text = normalize(' '.join(s.text for s in segments))
                others = [p for m, p in phrases.items() if m != model]
                decided, score = decide(phrases[model], text, others)
                auto = {'label': decided, 'text': text, 'score': round(score, 2), 'by': f'whisper {args.whisper_model}'}
                meta['auto_label'] = auto
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(meta, f, ensure_ascii=False, indent=1)
            label, how = auto['label'], 'Whisper'
        counts[(model, label, how)] = counts.get((model, label, how), 0) + 1

        base = os.path.basename(wav)
        if label == 'positiv':
            target = os.path.join(args.out, 'positives_real', model, 'auto_' + base)
        elif label == 'negativ':
            target = os.path.join(args.out, 'negatives_auto', model, base)
        else:
            unclear.append((model, base, (meta.get('auto_label') or {}).get('text', '')))
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not os.path.exists(target):
            shutil.copy2(wav, target)

    print('\nErgebnis (Modell / Bewertung / von):')
    for (model, label, how), n in sorted(counts.items()):
        print(f'  {model:24s} {label:8s} {how:10s} {n:5d}')
    if unclear:
        print('\nUnklar - bitte anhören (und ggf. auf dem Pi in der Prüfliste bewerten):')
        for model, base, text in unclear:
            print(f'  {model}/{base}: "{text}"')


if __name__ == '__main__':
    main()
