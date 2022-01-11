import os
import json
import pickle
import argparse
import numpy as np
from tqdm import tqdm
import random
from utils import *
from transformers import *

from parser.overnight import OvernightIRTranslator 
from bart2ir.predict import prepare

from utils.misc import init_vocab
from transformers import *

overnight_domains = ['basketball', 'blocks', 'calendar', 'housing', 'publications', 'recipes', 'restaurants', 'socialnetwork']

def read_data(path, domain_idx):
    ex_list = []
    with open(path, 'r') as infile:
        for line in infile:
            line = line.strip()
            if line == '':
                continue
            q, lf = line.split('\t')
            ex_list.append({"q": q.strip(), "lf": lf.strip(), "domain": domain_idx})
    return ex_list


def encode_dataset(dataset, vocab, tokenizer):
    irs = []
    targets = []
    domain_idx = []

    translator = OvernightIRTranslator.IR_translator()

    for item in tqdm(dataset):
        irs.append(translator.lambda_to_ir(item['lf']))
        targets.append(item['lf'])
        domain_idx.append(item['domain'])
    
    sequences = irs + targets
    encoded_inputs = tokenizer(sequences, padding = True)
    
    max_seq_length = len(encoded_inputs['input_ids'][0])
    assert max_seq_length == len(encoded_inputs['input_ids'][-1])

    input_ids = tokenizer.batch_encode_plus(irs, max_length = max_seq_length, pad_to_max_length = True, truncation = True)
    source_ids = np.array(input_ids['input_ids'], dtype = np.int32)
    source_mask = np.array(input_ids['attention_mask'], dtype = np.int32)
    target_ids = tokenizer.batch_encode_plus(targets, max_length = max_seq_length, pad_to_max_length = True, truncation = True)
    target_ids = np.array(target_ids['input_ids'], dtype = np.int32)
    
    choices = np.array([0]*len(irs), dtype = np.int32)
    answers = np.array(domain_idx, dtype = np.int32)

    return source_ids, source_mask, target_ids, choices, answers


def encode_test_dataset(predicted_ir, dataset, vocab, tokenizer):
    assert len(predicted_ir) == len(dataset)
    irs = []
    targets = []
    domain_idx = []

    translator = OvernightIRTranslator.IR_translator()

    for item in tqdm(dataset):
        irs = predicted_ir
        targets.append(item['lf'])
        domain_idx.append(item['domain'])
    
    sequences = irs + targets
    encoded_inputs = tokenizer(sequences, padding = True)

    max_seq_length = len(encoded_inputs['input_ids'][0])
    assert max_seq_length == len(encoded_inputs['input_ids'][-1])

    input_ids = tokenizer.batch_encode_plus(irs, max_length = max_seq_length, pad_to_max_length = True, truncation = True)
    source_ids = np.array(input_ids['input_ids'], dtype = np.int32)
    source_mask = np.array(input_ids['attention_mask'], dtype = np.int32)
    target_ids = tokenizer.batch_encode_plus(targets, max_length = max_seq_length, pad_to_max_length = True, truncation = True)
    target_ids = np.array(target_ids['input_ids'], dtype = np.int32)

    choices = np.array([0]*len(irs), dtype = np.int32)
    answers = np.array(domain_idx, dtype = np.int32)

    return source_ids, source_mask, target_ids, choices, answers



def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('--data_dir', required=True, help="path to dataset")
    parser.add_argument('--input_dir', required=True, help="path to processed NLQ2IR dataloaders")
    parser.add_argument('--output_dir', required=True)
    parser.add_argument('--model_name_or_path', required=True)
    parser.add_argument('--ckpt', required=True)
    parser.add_argument('--domain', choices=overnight_domains, default='all')

    # training parameters
    parser.add_argument('--batch_size', default=256, type=int)
    parser.add_argument('--seed', type=int, default=666, help='random seed')
    
    args = parser.parse_args()

    set_seed(666)
    args.domain = overnight_domains if args.domain == 'all' else [args.domain]

    print('Build kb vocabulary')
    vocab = {
        'answer_token_to_idx': {}
    }
    print('Load queries')

    train_set, val_set, test_set = [], [], []
    for domain in args.domain:
        idx = overnight_domains.index(domain)
        train_data = read_data(os.path.join(args.data_dir, domain + '_train.tsv'), idx)
        random.shuffle(train_data)
        train_set += train_data[:int(len(train_data) * 0.8)]
        val_set += train_data[int(len(train_data) * 0.8):]
        test_set += read_data(os.path.join(args.data_dir, domain + '_test.tsv'), idx)

    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir, exist_ok=True)

    fn = os.path.join(args.output_dir, 'vocab.json')
    print('Dump vocab to {}'.format(fn))

    with open(fn, 'w') as f:
        json.dump(vocab, f, indent=2)
    
    tokenizer = BartTokenizer.from_pretrained(args.model_name_or_path)
 
    for name, dataset in zip(('train', 'val', 'test'), (train_set, val_set, test_set)):
        if 'test' in name or 'val' in name:
            ir = [line.strip() for line in prepare(name, args)]
            outputs = encode_test_dataset(ir, dataset, vocab, tokenizer)
        else:
            outputs = encode_dataset(dataset, vocab, tokenizer)
            
        assert len(outputs) == 5
        
        with open(os.path.join(args.output_dir, '{}.pt'.format(name)), 'wb') as f:
            for o in outputs:
                pickle.dump(o, f)

if __name__ == '__main__':
    main()