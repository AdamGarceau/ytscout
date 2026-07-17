#!/usr/bin/env python3
"""
nano_banana.py — thumbnail generator on Google's nano banana (Gemini image model).

Uses YOUR Google AI Studio key (GEMINI_API_KEY), the cheap Google meter, not Fal.ai.
Reads the key from the environment or from ~/.gemini/.env. Never hardcode a key here.

Usage:
  python3 nano_banana.py --list                      # find the image model your key can call
  python3 nano_banana.py --check                     # confirm the key works + has quota (no image, ~free)
  python3 nano_banana.py --prompt "..." --out t.png  # text-to-image thumbnail
  python3 nano_banana.py --prompt "..." --ref you.jpg --out t.png   # image-to-image (keeps your face)

Deps: stdlib only.
"""
import os, sys, json, base64, argparse, ssl, urllib.request, urllib.error

# macOS Python.org builds don't trust the system cert store by default. Use certifi's
# bundle if present so HTTPS to Google works without the "Install Certificates" dance.
try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()

API = "https://generativelanguage.googleapis.com/v1beta"
# nano banana's model id has changed names across releases; try these in order.
IMAGE_MODEL_CANDIDATES = [
    "gemini-2.5-flash-image",
    "gemini-2.5-flash-image-preview",
    "gemini-2.0-flash-preview-image-generation",
    "imagen-3.0-generate-002",
]

def load_key():
    k = os.environ.get("GEMINI_API_KEY")
    if k:
        return k.strip()
    env = os.path.expanduser("~/.gemini/.env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None

def _get(url):
    with urllib.request.urlopen(url, timeout=30, context=_SSL) as r:
        return json.loads(r.read())

def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180, context=_SSL) as r:
        return json.loads(r.read())

def list_models(key):
    d = _get(f"{API}/models?key={key}")
    names = [m["name"].split("/")[-1] for m in d.get("models", [])]
    img = [n for n in names if "image" in n.lower() or "imagen" in n.lower()]
    print("Image-capable models on your key:")
    for n in (img or names):
        print("  -", n)
    return img

def pick_model(key):
    try:
        available = {m["name"].split("/")[-1] for m in _get(f"{API}/models?key={key}").get("models", [])}
    except Exception:
        available = set()
    for m in IMAGE_MODEL_CANDIDATES:
        if m in available:
            return m
    return IMAGE_MODEL_CANDIDATES[0]

def generate(key, prompt, ref=None, out="thumbnail.png", model=None):
    model = model or pick_model(key)
    parts = [{"text": prompt}]
    if ref:
        mime = "image/png" if ref.lower().endswith(".png") else "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime,
                     "data": base64.b64encode(open(ref, "rb").read()).decode()}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
    url = f"{API}/models/{model}:generateContent?key={key}"
    try:
        resp = _post(url, body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        sys.exit(f"  ✗ HTTP {e.code} on model '{model}': {detail}")
    # pull the first inline image out of the response
    for cand in resp.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = part.get("inline_data") or part.get("inlineData")
            if data and data.get("data"):
                open(out, "wb").write(base64.b64decode(data["data"]))
                print(f"  ✓ saved {out}  (model: {model})")
                return out
    sys.exit(f"  ✗ no image in response. model={model}, raw={json.dumps(resp)[:400]}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt")
    ap.add_argument("--ref", help="reference photo for image-to-image (keeps your face)")
    ap.add_argument("--out", default="thumbnail.png")
    ap.add_argument("--model", help="force a model id (else auto-pick)")
    ap.add_argument("--list", action="store_true", help="list image models your key can use")
    ap.add_argument("--check", action="store_true", help="confirm key + quota, no image")
    a = ap.parse_args()

    key = load_key()
    if not key:
        sys.exit("  ✗ GEMINI_API_KEY not set. Put your new AI Studio key in ~/.gemini/.env")

    if a.list:
        list_models(key); return
    if a.check:
        try:
            _get(f"{API}/models?key={key}")
            print("  ✓ key works and the API answered (quota is live).")
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            print(f"  ✗ HTTP {e.code}: {body}")
            if e.code == 429:
                print("  → still quota-blocked. Enable billing on this project, or the free tier is exhausted.")
        return
    if not a.prompt:
        sys.exit("  give me a --prompt (or use --check / --list first)")
    generate(key, a.prompt, ref=a.ref, out=a.out, model=a.model)

if __name__ == "__main__":
    main()
