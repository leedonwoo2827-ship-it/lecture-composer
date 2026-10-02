# Third-party licenses

## Supertonic (vendored helper)

`src/supertonic_tts/_vendor/supertonic_helper.py` is adapted from
`supertonic/py/helper.py` (https://github.com/supertone-inc/supertonic),
copyright Supertone, Inc., licensed under the MIT License.

Modifications:

1. Removed the GPU `NotImplementedError` guard, and added a
   `load_text_to_speech_with_providers` variant that accepts ONNX Runtime
   execution providers directly.
2. **Widened `AVAILABLE_LANGS` from 5 to 31 languages plus `"na"`.**
   The upstream list (`["en", "ko", "es", "pt", "fr"]`) was Supertonic 2's
   language set and was never updated for Supertonic 3. Because
   `_preprocess_text` raises `ValueError` for anything outside that list, the
   other 26 languages and the language-agnostic `"na"` mode were unreachable.
   The replacement list matches the "Supported Languages" table in the
   Supertonic 3 model card.

```
MIT License

Copyright (c) Supertone, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Supertonic 3 model assets

Downloaded separately by `setup.bat` from
https://huggingface.co/Supertone/supertonic-3 and licensed under
**OpenRAIL-M**. See the model card for usage restrictions. The model weights
are not redistributed with this project.

## Expression tag list

The three tags `<laugh>`, `<breath>` and `<sigh>` are named in the Supertonic 3
model card. The remaining seven (`<surprise>`, `<scream>`, `<throatclear>`,
`<sad>`, `<angry>`, `<cough>`, `<yawn>`) are documented in
https://github.com/Anonymzx/ComfyUI-Supertonic3TTS (MIT), whose table lists
exactly ten — matching the count Supertone states. They are labelled as
community-sourced throughout this app rather than presented as official.
