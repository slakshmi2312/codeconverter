import argparse
import os
from dataclasses import dataclass

from datasets import DatasetDict
from transformers import (
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

from dataset_loader import build_codet5_dataset, load_jsonl_records


@dataclass
class TrainConfig:
    train_jsonl: str
    output_dir: str
    val_jsonl: str | None = None
    model_name: str = "Salesforce/codet5-base"
    eval_ratio: float = 0.1
    max_input_length: int = 512
    max_target_length: int = 512
    batch_size: int = 4
    epochs: int = 3
    lr: float = 2e-5


def _tokenize_factory(tokenizer, max_input_length: int, max_target_length: int):
    def _tokenize(batch):
        model_inputs = tokenizer(
            batch["input_text"],
            truncation=True,
            max_length=max_input_length,
        )
        labels = tokenizer(
            text_target=batch["target_text"],
            truncation=True,
            max_length=max_target_length,
        )
        model_inputs["labels"] = labels["input_ids"]
        return model_inputs

    return _tokenize


def run_training(cfg: TrainConfig) -> None:
    train_records = load_jsonl_records(cfg.train_jsonl)
    train_ds = build_codet5_dataset(train_records)

    if cfg.val_jsonl:
        val_records = load_jsonl_records(cfg.val_jsonl)
        val_ds = build_codet5_dataset(val_records)
    else:
        split = train_ds.train_test_split(test_size=cfg.eval_ratio, seed=42)
        train_ds, val_ds = split["train"], split["test"]

    dataset = DatasetDict({"train": train_ds, "validation": val_ds})

    tokenizer = AutoTokenizer.from_pretrained(cfg.model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(cfg.model_name)

    tokenized = dataset.map(
        _tokenize_factory(tokenizer, cfg.max_input_length, cfg.max_target_length),
        batched=True,
        remove_columns=dataset["train"].column_names,
    )

    data_collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model)
    use_fp16 = os.getenv("DISABLE_FP16", "0") != "1"

    args = TrainingArguments(
        output_dir=cfg.output_dir,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        per_device_train_batch_size=cfg.batch_size,
        per_device_eval_batch_size=cfg.batch_size,
        learning_rate=cfg.lr,
        num_train_epochs=cfg.epochs,
        logging_steps=25,
        save_total_limit=3,
        fp16=use_fp16,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        tokenizer=tokenizer,
        data_collator=data_collator,
    )

    trainer.train()
    trainer.evaluate()
    trainer.save_model(cfg.output_dir)
    tokenizer.save_pretrained(cfg.output_dir)


def parse_args() -> TrainConfig:
    parser = argparse.ArgumentParser(description="Fine-tune CodeT5 for code-to-code translation.")
    parser.add_argument("--train_jsonl", required=True, help="Path to training dataset in JSONL format.")
    parser.add_argument("--val_jsonl", default=None, help="Optional validation dataset JSONL.")
    parser.add_argument("--output_dir", default="./models/codet5-finetuned", help="Checkpoint output directory.")
    parser.add_argument("--model_name", default="Salesforce/codet5-base", help="Base Hugging Face model.")
    parser.add_argument("--eval_ratio", type=float, default=0.1, help="Validation split ratio if val_jsonl absent.")
    parser.add_argument("--max_input_length", type=int, default=512)
    parser.add_argument("--max_target_length", type=int, default=512)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-5)
    args = parser.parse_args()
    return TrainConfig(
        train_jsonl=args.train_jsonl,
        val_jsonl=args.val_jsonl,
        output_dir=args.output_dir,
        model_name=args.model_name,
        eval_ratio=args.eval_ratio,
        max_input_length=args.max_input_length,
        max_target_length=args.max_target_length,
        batch_size=args.batch_size,
        epochs=args.epochs,
        lr=args.lr,
    )


if __name__ == "__main__":
    config = parse_args()
    run_training(config)
