from typing import Dict, List, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline


SUPPORTED_LANGUAGES = ["python", "java", "c", "javascript"]


def _seed_samples() -> List[Tuple[str, str]]:
    # Lightweight in-repo training set for runtime ML detection.
    return [
        ("python", "def add(a, b):\n    return a + b\nprint(add(1, 2))"),
        ("python", "for i in range(5):\n    print(i)"),
        ("python", "class User:\n    def __init__(self, name):\n        self.name = name"),
        ("python", "if __name__ == '__main__':\n    print('run')"),
        ("python", "nums = [1,2,3]\nfor n in nums:\n    print(n)"),
        ("java", "public class Main { public static void main(String[] args){ System.out.println(\"hi\"); } }"),
        ("java", "class A { int x = 10; void show(){ System.out.println(x); } }"),
        ("java", "for (int i = 0; i < 10; i++) { System.out.println(i); }"),
        ("java", "import java.util.*; List<Integer> a = new ArrayList<>();"),
        ("java", "public static int add(int a, int b){ return a + b; }"),
        ("c", "#include <stdio.h>\nint main(){ printf(\"hello\\n\"); return 0; }"),
        ("c", "int add(int a, int b){ return a + b; }"),
        ("c", "for(int i=0;i<5;i++){ printf(\"%d\", i); }"),
        ("c", "scanf(\"%d\", &n);"),
        ("c", "#include <stdlib.h>\nchar *p = (char*)malloc(10);"),
        ("javascript", "function add(a, b) { return a + b; }\nconsole.log(add(1,2));"),
        ("javascript", "const nums = [1,2,3]; nums.forEach(n => console.log(n));"),
        ("javascript", "class User { constructor(name){ this.name = name; } }"),
        ("javascript", "let x = 5; if (x > 3) { console.log('ok'); }"),
        ("javascript", "import React from 'react'; export default function App(){ return <div/>; }"),
    ]


class MLLanguageDetector:
    def __init__(self) -> None:
        self.model = self._fit_model()

    def _fit_model(self) -> Pipeline:
        samples = _seed_samples()
        X = [code for _, code in samples]
        y = [lang for lang, _ in samples]
        pipeline = Pipeline(
            steps=[
                (
                    "tfidf",
                    TfidfVectorizer(
                        analyzer="char_wb",
                        ngram_range=(2, 5),
                        lowercase=False,
                        min_df=1,
                    ),
                ),
                ("clf", MultinomialNB(alpha=0.1)),
            ]
        )
        pipeline.fit(X, y)
        return pipeline

    def predict(self, code: str) -> Dict[str, object]:
        text = (code or "").strip()
        if not text:
            return {"language": "unknown", "confidence": 0.0}

        proba = self.model.predict_proba([text])[0]
        classes = self.model.classes_
        idx = int(np.argmax(proba))
        lang = str(classes[idx])
        confidence = float(proba[idx])
        return {"language": lang, "confidence": confidence}
