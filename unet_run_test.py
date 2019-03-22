from __future__ import division

'-------------------------------------------------------------------'
import os
import glob
import functools

from keras.models import load_model
import numpy as np
np.set_printoptions(threshold=np.nan)

from Bio import pairwise2

import pylab as plt

import tqdm

three_to_one = {'ASP': 'D', 'GLU': 'E', 'ASN': 'N', 'GLN': 'Q', 'ARG': 'R', 'LYS': 'K', 'PRO': 'P', 'GLY': 'G',
                'CYS': 'C', 'THR': 'T', 'SER': 'S', 'MET': 'M', 'TRP': 'W', 'PHE': 'F', 'TYR': 'Y', 'HIS': 'H',
                'ALA': 'A', 'VAL': 'V', 'LEU': 'L', 'ILE': 'I', 'MSE': 'M'}

prob_len = 5

#bins = [0, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 14.5, 15, 15.5, 16]
bins = [0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
'-------------------------------------------------------------------'
# Support to build functions

def _strip(x):
    return len(x[1].strip('-'))

def pick_best_alignment(align, sequence):
    align_1 = [al for al in align if al[0] == sequence]
    if align_1:
        if len(align_1) == 1:
            al = align_1[0]
        else:
            al = min(align_1, key=_strip)
    else:
        al = align[0]
    return al

@functools.lru_cache(maxsize=512)
def parse_pdb(pdb):
    ca = dict()
    cb = dict()

    this_chain = pdb.split('/')[-2][-1]
    fa = pdb.replace('native.pdb', 'sequence.fa')
    seq = ''.join(line.strip() for line in open(fa) if not line.startswith('>'))
    pdb_seq = dict()
    pdb_numbers = []
    for line in open(pdb):
        if line.startswith('ATOM'):
            type_ = line[13:15]
            chain = line[21:22]
            if type_ == 'CA' and chain == this_chain:
                resi = int(line[22:26])
                if resi not in pdb_seq:
                    pdb_seq[resi] = three_to_one[line[17:20]]
                    pdb_numbers.append(resi)

    pdb_seq_merged = ''.join(pdb_seq[k] for k in sorted(pdb_seq))

    aligned = pairwise2.align.globalmd(seq, pdb_seq_merged, 5, -1, -5, -3, -0.5, -0.1)
    if len(aligned) == 0:
        aligned = pairwise2.align.globalmd(seq, pdb_seq_merged, 5, -1, -3, -3, -0.5, -0.1)
        if len(aligned) == 0:
            aligned = pairwise2.align.localmd(seq, pdb_seq_merged, 10, -1, -3, -3, -0.5, -0.1)

    aligned = pick_best_alignment(aligned, seq)

    res_mapping = dict()
    j = 0
    for i, aa in enumerate(aligned[1]):
        if aa != '-':
            skipped = aligned[0][:j].count('-')  # Count for gaps in the sequence
            pdb_number = pdb_numbers[j]
            res_mapping[pdb_number] = i + 1 - skipped
            j += 1

    for line in open(pdb):
        if not line.startswith('ATOM'):
            continue
        type_ = line[13:15]
        chain = line[21:22]
        if type_ not in ('CA', 'CB') or chain != this_chain:
            continue
        resi = res_mapping[int(line[22:26])]
        x = float(line[30:38])
        y = float(line[38:46])
        z = float(line[46:54])
        coord = np.array([x, y, z], dtype=np.float32)

        if type_ == 'CA':
            ca[resi] = coord
        else:
            cb[resi] = coord

    # Overwrite CB
    ca.update(cb)

    cmap = dict()
    for i in ca:
        for j in ca:
            if abs(i - j) > 5 and j > i:
                cmap[(i, j)] = np.linalg.norm(ca[i] - ca[j])
    return cmap

def parse_contact_matrix(data):
    contacts = dict()
    #new_data = (data + data.T) / 2
    for i in range(data.shape[0] - 4):
        for j in range(i + 5, data.shape[1]):
            contacts[(i + 1, j + 1)] = data[i, j]

    return contacts

'-------------------------------------------------------------------'
#Performance metrics (absolute error, relative error)

def error_metrics(contacts, pdb_parsed):
    actual_pdb = {}
    pred_contacts = {}
    pred_zipped = {}
    pred_single = {}
    ind_dict = {}

    for k, v in pdb_parsed.items():
        if (v < 8):
            actual_pdb[k] = v

    for k, v in contacts.items():
        if k in actual_pdb.keys():
            pred_contacts[k] = v
            

    for k, v in (pred_contacts.items()):
        pred_zipped[k] =  [i*j for i, j in zip(v, bins)]
    
    #print (pred_zipped)

    for k, v in pred_zipped.items():
        sum_prob = 0
        count = 0
        for n in v:
            if count <=  prob_len:
                sum_prob += n
                count += 1
            else:
                break
        
        pred_single[k] = (sum_prob)

    #print (pred_single)
    #print (actual_pdb)

    abs_error = []
    rel_error = []

    for (k,v), (k1,v1) in zip (pred_single.items(), actual_pdb.items()):
        abs_error.append(abs(v - v1))
        rel_error.append((abs(v-v1))/((v+v1)/2)) 

    return abs_error, rel_error

# Performance metrics (Precision, Recall, F1)
def alt_metrics(contacts, pdb_parsed):
    actual_pdb = {}
    pred_zipped = {}
    pred_single = {}
    pred_single_15 = {}
    
    for k, v in pdb_parsed.items():
        if (v < 8):
            actual_pdb[k] = v

    for k, v in (contacts.items()):
        pred_zipped[k] =  [i*j for i, j in zip(v, bins)]
    
    for k, v in pred_zipped.items():
        sum_prob = 0
        count = 0
        for n in v:
            if count <=  prob_len:
                sum_prob += n
                count += 1
            else:
                break
        
        pred_single[k] = (sum_prob)

    prec = []
    rec = []
    f1 = []

    for k, v in pred_single.items():
        if (v < 8):
            pred_single_15[k] = v


    for k, v in pred_single.items():
        count_n = 0
        count_p = 0 
        if k in (actual_pdb.keys()):
            count_n += 1
            if (v < 8):
                count_p += 1

        if count_n == 0:
            count_n = 1
        prec.append(count_p/count_n)
        
    for k, v in pdb_parsed.items():
        count_n = 0
        count_p = 0 
        if k in (pred_single_15.keys()):
            count_n += 1
            if (v < 8):
                count_p += 1

        if count_n == 0:
            count_n = 1
        rec.append(count_p/count_n)
    
    #f1.append(((2*i*j)/(i+j)) for i, j in zip(prec, rec))
    

    return prec, rec

'-------------------------------------------------------------------'

lengths = dict((line.split(',')[0], int(line.split(',')[1])) for line in open('/home/ashenoy/ashenoy/david_retrain_pconsc4/testing/benchmark_set/lengths.txt'))

model_name = 'M_12_E100_mae_trained'
model_n = 'M_12_E100'

m = load_model('{}.h5'.format(model_name))

'''
import pickle
out_pred = 'results_15_8A_{}'.format(model_name)
print()
print(out_pred)
print()
output = open(out_pred, 'wb')
'''

out_pm = '15P_results_{}'.format(model_name)
print()
print(out_pm)
print()
output = open(out_pm, 'w')

for epoch in tqdm.trange(1, 100, desc = 'Epoch'):

    weights_path = 'models/{}/{}_epo{:02d}-*.h5'.format(model_name, model_n, epoch)

    weights = glob.glob(weights_path)[0]

    m.load_weights(weights)

    #ppv = []

    for data_file in tqdm.tqdm(glob.glob('/home/ashenoy/ashenoy/david_retrain_pconsc4/testing/testing_sample/benchmark_set/*.npz'), desc='Protein'):
        data_batch = dict(np.load(data_file))
        data_batch['mask'][:] = 1

        pred = m.predict(data_batch)[0]
        #print (pred)
        print (pred.shape)       
        
        '''
        #Save predictions to file
        output = open(out_pred, 'wb')
        pickle.dump(pred, output)
        print()
        output.close()
        '''

        prot_name = data_file.split('/')[-1].split('.')[0]
        length = lengths[prot_name]
        
        pdb_parsed = parse_pdb('/home/ashenoy/ashenoy/david_retrain_pconsc4/testing/testing_sample/benchmarkset/{}/native.pdb'.format(prot_name))
        contacts_parsed = parse_contact_matrix(pred.squeeze())

        ab_error, rel_error = error_metrics(contacts_parsed, pdb_parsed)
        prec, recall = alt_metrics(contacts_parsed, pdb_parsed)

        #Save metrics to file
        output = open(out_pm, 'w')
        print(epoch, np.mean(ab_error), np.median(ab_error), np.mean(rel_error), np.median(rel_error), (np.mean(prec)*100), (np.mean(recall)*100), file=output, flush=True)
        print()
        print()
        output.close()

#os.system('cat results_*')

'-------------------------------------------------------------------'


