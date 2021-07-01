# Copyright (c) 2021 PaddlePaddle Authors. All Rights Reserved.
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

import numpy as np
import paddle
from paddle import inference
from paddlenlp.data import JiebaTokenizer, Stack, Tuple, Pad, Vocab
from scipy.special import softmax

# yapf: disable
parser = argparse.ArgumentParser()
parser.add_argument("--model_file", type=str, required=True,
    default='./static_graph_params.pdmodel', help="The path to model info in static graph.")
parser.add_argument("--params_file", type=str, required=True,
    default='./static_graph_params.pdiparams', help="The path to parameters in static graph.")
parser.add_argument("--vocab_path", type=str, default="./robot_chat_word_dict.txt", help="The path to vocabulary.")
parser.add_argument("--max_seq_length",
    default=128, type=int, help="The maximum total input sequence length after tokenization. "
    "Sequences longer than this will be truncated, sequences shorter will be padded.")
parser.add_argument("--batch_size", default=2, type=int, help="Batch size per GPU/CPU for training.")
parser.add_argument('--device', choices=['cpu', 'gpu', 'xpu'],
    default="gpu", help="Select which device to train model, defaults to gpu.")
args = parser.parse_args()
# yapf: enable


def preprocess_prediction_data(text, tokenizer):
    """
    It process the prediction data as the format used as training.

    Args:
        text (obj:`str`): The input text.
        tokenizer(obj: `paddlenlp.data.JiebaTokenizer`): It use jieba to cut the chinese string.

    Returns:
        input_ids (obj: `list[int]`): The word ids of the `text`.
        seq_len (obj: `int`): The length of words.
    """
    input_id = tokenizer.encode(text)
    seq_len = len(input_id)
    return input_id, seq_len


class Predictor(object):
    def __init__(self, model_file, params_file, device, max_seq_length):
        self.max_seq_length = max_seq_length

        config = paddle.inference.Config(model_file, params_file)
        if device == "gpu":
            # set GPU configs accordingly
            config.enable_use_gpu(100, 0)
        elif device == "cpu":
            # set CPU configs accordingly,
            # such as enable_mkldnn, set_cpu_math_library_num_threads
            config.disable_gpu()
        elif device == "xpu":
            # set XPU configs accordingly
            config.enable_xpu(100)
        config.switch_use_feed_fetch_ops(False)
        self.predictor = paddle.inference.create_predictor(config)

        self.input_handles = [
            self.predictor.get_input_handle(name)
            for name in self.predictor.get_input_names()
        ]

        self.output_handle = self.predictor.get_output_handle(
            self.predictor.get_output_names()[0])

    def predict(self,
                data,
                tokenizer,
                label_map,
                batch_size=1,
                pad_token_id=0,
                max_gram_filter_size=3):
        """
        Predicts the data labels.

        Args:
            model (obj:`paddle.nn.Layer`): A model to classify texts.
            data (obj:`List(Example)`): The processed data whose each element is a Example (numedtuple) object.
                A Example object contains `text`(word_ids) and `se_len`(sequence length).
            tokenizer(obj:`PretrainedTokenizer`): This tokenizer inherits from 
                :class:`~paddlenlp.transformers.PretrainedTokenizer` which contains most of the methods.
                 Users should refer to the superclass for more information regarding methods.
            label_map(obj:`dict`): The label id (key) to label str (value) map.
            batch_size(obj:`int`, defaults to 1): The number of batch.

        Returns:
            results(obj:`dict`): All the predictions labels.
        """
        examples = []
        for text in data:
            input_id, seq_len = preprocess_prediction_data(text, tokenizer)
            # Sequence length should larger or equal than the maximum ngram_filter_size in TextCNN model
            if seq_len < max_gram_filter_size:
                input_id.extend([pad_token_id] * (max_gram_filter_size - seq_len))
                seq_len = max_gram_filter_size
            examples.append((input_id, seq_len))

        batchify_fn = lambda samples, fn=Tuple(
            Pad(axis=0, pad_val=tokenizer.vocab.token_to_idx.get("[PAD]", 0)),  # input_id
            Stack()  # seq_len
        ): fn(samples)

        # Seperates data into some batches.
        batches = [
            examples[idx:idx + batch_size]
            for idx in range(0, len(examples), batch_size)
        ]

        results = []
        for batch in batches:
            input_ids, seq_lens = batchify_fn(batch)
            self.input_handles[0].copy_from_cpu(input_ids)
            self.predictor.run()
            logits = self.output_handle.copy_to_cpu()
            probs = softmax(logits, axis=1)
            print(probs)
            idx = np.argmax(probs, axis=1)
            idx = idx.tolist()
            labels = [label_map[i] for i in idx]
            results.extend(labels)
        return results


if __name__ == "__main__":
    # Define predictor to do prediction.
    predictor = Predictor(args.model_file, args.params_file, args.device,
                          args.max_seq_length)

    # Firstly pre-processing prediction data  and then do predict.
    data = [
        '你再骂我我真的不跟你聊了',
        '你看看我附近有什么好吃的',
        '我喜欢画画也喜欢唱歌'
    ]
    vocab = Vocab.load_vocabulary(
        args.vocab_path, unk_token='[UNK]', pad_token='[PAD]')
    pad_token_id = vocab.to_indices('[PAD]')
    tokenizer = JiebaTokenizer(vocab)
    label_map = {0: 'negative', 1: 'neutral', 2: 'positive'}

    results = predictor.predict(
        data,
        tokenizer,
        label_map,
        batch_size=args.batch_size,
        pad_token_id=pad_token_id)
    for idx, text in enumerate(data):
        print('Data: {} \t Label: {}'.format(text, results[idx]))
