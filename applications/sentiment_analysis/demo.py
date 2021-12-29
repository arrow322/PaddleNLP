# Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import paddle
from paddlenlp.transformers import SkepTokenizer, SkepForTokenClassification, SkepForSequenceClassification
from utils import load_dict
from seqeval.metrics.sequence_labeling import get_entities


def decoding(text, tag_seq):
    assert len(text) == len(
        tag_seq), f"text len: {len(text)}, tag_seq len: {len(tag_seq)}"

    puncs = list(",.?;!，。？；！")
    splits = [idx for idx in range(len(text)) if text[idx] in puncs]

    prev = 0
    sub_texts, sub_tag_seqs = [], []
    for i, split in enumerate(splits):
        sub_tag_seqs.append(tag_seq[prev:split])
        sub_texts.append(text[prev:split])
        prev = split
    sub_tag_seqs.append(tag_seq[prev:])
    sub_texts.append((text[prev:]))

    ents_list = []
    for sub_text, sub_tag_seq in zip(sub_texts, sub_tag_seqs):
        ents = get_entities(sub_tag_seq, suffix=False)
        ents_list.append((sub_text, ents))

    aps = []
    no_a_words = []
    for sub_tag_seq, ent_list in ents_list:
        sub_aps = []
        sub_no_a_words = []
        for ent in ent_list:
            ent_name, start, end = ent
            if ent_name == "Aspect":
                aspect = sub_tag_seq[start:end + 1]
                sub_aps.append([aspect])
                if len(sub_no_a_words) > 0:
                    sub_aps[-1].extend(sub_no_a_words)
                    sub_no_a_words.clear()
            else:
                ent_name == "Opinion"
                opinion = sub_tag_seq[start:end + 1]
                if len(sub_aps) > 0:
                    sub_aps[-1].append(opinion)
                else:
                    sub_no_a_words.append(opinion)

        if sub_aps:
            aps.extend(sub_aps)
            if len(no_a_words) > 0:
                aps[-1].extend(no_a_words)
                no_a_words.clear()
        elif sub_no_a_words:
            if len(aps) > 0:
                aps[-1].extend(sub_no_a_words)
            else:
                no_a_words.extend(sub_no_a_words)

    if no_a_words:
        no_a_words.insert(0, "None")
        aps.append(no_a_words)

    return aps


def is_aspect_first(text, aspect, opinion_word):
    return text.find(aspect) <= text.find(opinion_word)


def concate_aspect_and_opinion(text, aspect, opinion_words):
    aspect_text = ""
    for opinion_word in opinion_words:
        if is_aspect_first(text, aspect, opinion_word):
            aspect_text += aspect + opinion_word + "，"
        else:
            aspect_text += opinion_word + aspect + "，"
    aspect_text = aspect_text[:-1]

    return aspect_text


def format_print(results):
    for result in results:
        aspect, opinions, sentiment = result["aspect"], result[
            "opinions"], result["sentiment_polarity"]
        print(
            f"aspect: {aspect}, opinions: {opinions}, sentiment_polarity: {sentiment}"
        )
    print()


def predict(ext_model,
            cls_model,
            tokenizer,
            ext_id2label,
            cls_id2label,
            max_seq_len=512):

    ext_model.eval()
    cls_model.eval()

    while True:
        input_text = input("input text: \n")
        if not input_text:
            continue
        if input_text == "quit":
            break

        input_text = input_text.strip().replace(" ", "")
        # processing input text
        encoded_inputs = tokenizer(
            list(input_text),
            is_split_into_words=True,
            max_seq_len=max_seq_len, )
        input_ids = paddle.to_tensor([encoded_inputs["input_ids"]])
        token_type_ids = paddle.to_tensor([encoded_inputs["token_type_ids"]])

        # extract aspect and opinion words
        logits = ext_model(input_ids, token_type_ids=token_type_ids)
        predictions = logits.argmax(axis=2).numpy()[0]
        tag_seq = [ext_id2label[idx] for idx in predictions][1:-1]
        aps = decoding(input_text, tag_seq)

        # predict sentiment for aspect with cls_model
        results = []
        for ap in aps:
            aspect = ap[0]
            opinion_words = list(set(ap[1:]))
            aspect_text = concate_aspect_and_opinion(input_text, aspect,
                                                     opinion_words)

            encoded_inputs = tokenizer(
                aspect_text,
                text_pair=input_text,
                max_seq_len=max_seq_len,
                return_length=True)
            input_ids = paddle.to_tensor([encoded_inputs["input_ids"]])
            token_type_ids = paddle.to_tensor(
                [encoded_inputs["token_type_ids"]])

            logits = cls_model(input_ids, token_type_ids=token_type_ids)
            prediction = logits.argmax(axis=1).numpy()[0]

            result = {
                "aspect": aspect,
                "opinions": opinion_words,
                "sentiment_polarity": cls_id2label[prediction]
            }
            results.append(result)

        format_print(results)


if __name__ == "__main__":
    # yapf: disable
    parser = argparse.ArgumentParser()
    parser.add_argument("--ext_model_path", type=str, default=None, help="The path of extraction model path that you want to load.")
    parser.add_argument("--cls_model_path", type=str, default=None, help="The path of classification model path that you want to load.")
    parser.add_argument("--ext_label_path", type=str, default=None, help="The path of extraction label dict.")
    parser.add_argument("--cls_label_path", type=str, default=None, help="The path of classification label dict.")
    parser.add_argument("--max_seq_len", type=int, default=512, help="The maximum total input sequence length after tokenization.")
    args = parser.parse_args()
    # yapf: enbale

    # load dict
    model_name = "skep_ernie_1.0_large_ch"
    ext_label2id, ext_id2label = load_dict(args.ext_label_path)
    cls_label2id, cls_id2label = load_dict(args.cls_label_path)
    tokenizer = SkepTokenizer.from_pretrained(model_name)
    print("label dict loaded.")

    # load ext model
    ext_state_dict = paddle.load(args.ext_model_path)
    ext_model = SkepForTokenClassification.from_pretrained(model_name, num_classes=len(ext_label2id))
    ext_model.load_dict(ext_state_dict)
    print("extraction model loaded.")

    # load cls model
    cls_state_dict = paddle.load(args.cls_model_path)
    cls_model = SkepForSequenceClassification.from_pretrained(model_name, num_classes=len(cls_label2id))
    cls_model.load_dict(cls_state_dict)
    print("classification model loaded.")

    # do predict
    predict(ext_model, cls_model, tokenizer, ext_id2label, cls_id2label,  max_seq_len=args.max_seq_len)
