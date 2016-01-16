#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Licensed under the GNU Affero General Public License, version 3 - http://www.gnu.org/licenses/agpl-3.0.html

from Queue import Queue

from numpy import zeros, random, sum as np_sum, add as np_add, concatenate, \
    repeat as np_repeat, array, float32 as REAL, empty, ones, memmap as np_memmap, \
    sqrt, newaxis, ndarray, dot, vstack, dtype, divide as np_divide

import gensim.models.word2vec
import gensim.models.doc2vec 

from six.moves import xrange, zip
from six import string_types, integer_types, itervalues

import sys
import random

import numpy as np
import operator

import keras.constraints

from keras.utils.np_utils import accuracy
from keras.models import Graph,Sequential
from keras.layers.core import Dense, Dropout, Activation, Merge, Flatten, LambdaMerge,Lambda
from keras.layers.embeddings import Embedding
#from keras.optimizers import SGD
from keras.objectives import mse

from word2veckeras import train_sg_pair,train_cbow_pair,queue_to_list


def train_batch_dbow(model,
                     docs, alpha,
                     work=None,
                     train_words=False, learn_doctags=True, learn_words=True, learn_hidden=True,
                     word_vectors=None, word_locks=None, doctag_vectors=None, doctag_locks=None,
                     batch_size=100):
    #print 'train_batch_dbow'
    batch_count=0
    train_x0=[[0]]*batch_size
    train_x1=[[0]]*batch_size
    train_y=[[0]]*batch_size
    while 1:
        for doc in docs:
            for doctag_index in doc.tags:
                for word in doc.words:
                    xy=train_sg_pair(model, word, doctag_index, alpha, learn_vectors=learn_doctags,
                              learn_hidden=learn_hidden, context_vectors=doctag_vectors,
                              context_locks=doctag_locks)
                    if xy !=None:
                        (x0,x1,y)=xy
                        #print xy
                        train_x0[batch_count]=[x0]
                        train_x1[batch_count]=x1
                        train_y[batch_count]=y
                        batch_count += 1
                        if batch_count >= batch_size :
                            yield { 'index':np.array(train_x0), 'point':np.array(train_x1), 'code':np.array(train_y)}
                            batch_count=0

                            
def train_batch_dm_xy_generator(model, docs):
    for doc in docs:
        indexed_doctags = model.docvecs.indexed_doctags(doc.tags)
        doctag_indexes, doctag_vectors, doctag_locks, ignored = indexed_doctags

        word_vocabs = [model.vocab[w] for w in doc.words if w in model.vocab and
                           model.vocab[w].sample_int > model.random.rand() * 2**32]
        for pos, word in enumerate(word_vocabs):
            reduced_window = model.random.randint(model.window)  # `b` in the original doc2vec code
            start = max(0, pos - model.window + reduced_window)
            window_pos = enumerate(word_vocabs[start:(pos + model.window + 1 - reduced_window)], start)
            word2_indexes = [word2.index for pos2, word2 in window_pos if pos2 != pos]
                
            xy=train_cbow_pair(model, word, word2_indexes) #, l1=None, alpha=None,learn_vectors=False, learn_hidden=learn_hidden)
            x2=doctag_indexes
            yield [xy[0],x2,xy[1],xy[2]]
            
                           
def train_batch_dm(model, docs,batch_size=100):
    w_len_queue_dict={}
    w_len_queue=[]
    while 1:
       for xy in train_batch_dm_xy_generator(model,docs):
            if xy != None:
                #print xy
                w_len=len(xy[0])
                if w_len>0:
                    if w_len not in w_len_queue_dict:
                        w_len_queue_dict[w_len]=Queue()
                        w_len_queue.append(w_len)
                    w_len_queue_dict[w_len].put(xy)
            for w_len in w_len_queue:
                #print w_len,w_len_queue_dict[w_len]._qsize()
                if w_len_queue_dict[w_len].qsize() >= batch_size :
                    #print w_len_queue_dict[w_len]
                    l=queue_to_list(w_len_queue_dict[w_len],batch_size)
                    #train=zip(l)
                    #print [w_len,len(l),[[wl,w_len_queue_dict[wl].qsize()] for wl in w_len_queue ]]
                    train=[[e[i] for e in l] for i in range(4)]
                    yield {'iword':np.array(train[0]),
                           'index':np.array(train[1]),
                            'point':np.array(train[2]),
                            'code':np.array(train[3])}
                    
def train_document_dm_concat_xy_generator(model, docs):
    for doc in docs:
        indexed_doctags = model.docvecs.indexed_doctags(doc.tags)
        doctag_indexes, doctag_vectors, doctag_locks, ignored = indexed_doctags

        word_vocabs = [model.vocab[w] for w in doc.words if w in model.vocab and
                       model.vocab[w].sample_int > model.random.rand() * 2**32]
        #doctag_len = len(doctag_indexes)
        #if doctag_len != model.dm_tag_count:

        null_word = model.vocab['\0']
        pre_pad_count = model.window
        post_pad_count = model.window
        padded_document_indexes = (
            (pre_pad_count * [null_word.index])  # pre-padding
            + [word.index for word in word_vocabs if word is not None]  # elide out-of-Vocabulary words
            + (post_pad_count * [null_word.index])  # post-padding
        )

        for pos in range(pre_pad_count, len(padded_document_indexes) - post_pad_count):
            word_context_indexes = (
                padded_document_indexes[(pos - pre_pad_count): pos]  # preceding words
                + padded_document_indexes[(pos + 1):(pos + 1 + post_pad_count)]  # following words
            )
            #word_context_len = len(word_context_indexes)
            #print word_context_len
            predict_word = model.vocab[model.index2word[padded_document_indexes[pos]]]
            xy = train_cbow_pair(model, predict_word, word_context_indexes)
            x2=doctag_indexes
            xy1=[xy[0],x2,xy[1],xy[2]]
            yield xy1
 
def train_document_dm_concat(model, docs,batch_size=100):
    batch_count=0
    train_t=[0]*batch_size
    #train=[[[0]]*batch_size]*4
    #print train_t
    # train_x1=[[0]]*batch_size
    # train_y=[[0]]*batch_size
    while 1:
        for xy in train_document_dm_concat_xy_generator(model,docs):
            train_t[batch_count]=xy
            # for i in range(4):
            #     print xy[i]
            #     train[i][batch_count]=xy[i]
            #print xy,batch_count
            #print train_t
            batch_count += 1
            if batch_count >= batch_size :
                #print '---'
                train=[[train_t[j][i] for j in range(batch_size) ] for i in range(4)]
                #print train
                yield {'iword':np.array(train[0]),
                           'index':np.array(train[1]),
                            'point':np.array(train[2]),
                            'code':np.array(train[3])}
                batch_count=0
                      
def build_keras_model_dbow(index_size,vector_size,vocab_size,code_dim,learn_doctags=True, learn_words=True, learn_hidden=True,model=None):
    # vocab_size=len(vocab)
    # #index_size=vocab_size
    # index_size=len(docvecs)
    # code_dim=vocab_size
    # #print 'build_keras_model',vocab_size, index_size, code_dim

    kerasmodel = Graph()
    kerasmodel.add_input(name='point', input_shape=(code_dim,), dtype=REAL)
    kerasmodel.add_node(kerasmodel.inputs['point'],name='pointnode')
    
    kerasmodel.add_input(name='index' , input_shape=(1,), dtype=int)

    kerasmodel.add_node(Embedding(index_size, vector_size, input_length=1),name='embedding', input='index')
    kerasmodel.add_node(Flatten(),name='embedflatten',input='embedding')
    kerasmodel.add_node(Dense(code_dim, activation='sigmoid',b_constraint = keras.constraints.maxnorm(0)), name='sigmoid', input='embedflatten')
    kerasmodel.add_output(name='code',inputs=['sigmoid','pointnode'], merge_mode='mul')
    kerasmodel.compile('rmsprop', {'code':'mse'})

    return kerasmodel


def build_keras_model_dm(index_size,vector_size,vocab_size,code_dim,learn_doctags=True, learn_words=True, learn_hidden=True, model=None ,word_vectors=None,doctag_vectors=None):
    #print 'build_keras_model_dm',index_size,vector_size,vocab_size,code_dim
    #vocab_size=len(model.vocab)
    ## #index_size=vocab_size
    #index_size=len(self.docvecs) 
    #code_dim=vocab_size
    #vector_size=model.vector_size

    # index_size=2
    # vocab_size=3
    # vector_size=2
    # code_dim=2
    # maxlen=1

    # # learn_doctags=False
    # # learn_words=False
    # # learn_hidden=False

    # learn_doctags=True
    # learn_words=True
    # learn_hidden=True

    
    kerasmodel = Graph()

    kerasmodel.add_input(name='iword' , input_shape=(1,), dtype=int)
    kerasmodel.add_input(name='index' , input_shape=(1,), dtype=int)
    
    embedword=Embedding(vocab_size, vector_size,trainable=learn_words,
                        #input_length=2,
                        #weights=[np.array([[1,2],[3,4],[5,6]],'float32')]
                        weights=[model.syn0]
                        )
    kerasmodel.add_node(
        embedword,
        name='embedword', input='iword')
    kerasmodel.add_node(Lambda(lambda x:x.mean(-2),output_shape=(vector_size,)),name='averageword',input='embedword')

    embedindex=Embedding(index_size, vector_size,trainable=learn_doctags,
                         #input_length=1,
                         #weights=[np.array([[10,20],[30,40]],'float32')]
                         weights=[model.docvecs.doctag_syn0]
           )
    kerasmodel.add_node(
        embedindex,
        name='embedindex', input='index')
    kerasmodel.add_node(Lambda(lambda x:x.mean(-2),output_shape=(vector_size,)),name='averageindex',input='embedindex')

    ### This calcuation diffrent from original gensim. Because of this error https://github.com/fchollet/keras/issues/1474
    kerasmodel.add_node(
        Merge([kerasmodel.nodes['averageword'],kerasmodel.nodes['averageindex']], mode='sum')
        #,output_shape=(vector_size,)
        ,name='average'
        #,name='sumembed'
        )
    if model.hs:
        hidden=Dense(code_dim, activation='sigmoid',b_constraint = keras.constraints.maxnorm(0),
                     trainable=learn_hidden,
                     weights=[model.syn1.T,np.zeros((code_dim))]
                     )
    else:
        hidden=Dense(code_dim, activation='sigmoid',b_constraint = keras.constraints.maxnorm(0),
                     trainable=learn_hidden,
                     weights=[model.syn1neg.T,np.zeros((code_dim))]
                     )
        
    kerasmodel.add_node(
        hidden
        , name='sigmoid', input='average')


    kerasmodel.add_input(name='point', input_shape=(code_dim,), dtype=REAL)
    kerasmodel.add_node(kerasmodel.inputs['point'],name='pointnode')

    kerasmodel.add_output(name='code',inputs=['sigmoid','pointnode'], merge_mode='mul')

    kerasmodel.compile('rmsprop', {'code':'mse'})
    #print kerasmodel.predict({'index':np.array([[0],[1]]),'iword':np.array([[1,0],[1,1]]),'point':np.array([[1,1],[1,1]] )  })
    
    return kerasmodel
    
    
def build_keras_model_dm_concat(index_size,vector_size,vocab_size,code_dim,learn_doctags=True, learn_words=True, learn_hidden=True, model=None ,word_vectors=None,doctag_vectors=None):
    # index_size=2
    # vocab_size=3
    # vector_size=2
    # code_dim=2
    # maxlen=1

    # learn_doctags=False
    # learn_words=False
    # learn_hidden=False

    # learn_doctags=True
    # learn_words=True
    # learn_hidden=True

    kerasmodel = Graph()


    kerasmodel.add_input(name='iword' , input_shape=(1,), dtype=int)
    kerasmodel.add_input(name='index' , input_shape=(1,), dtype=int)


    embedword=Embedding(vocab_size, vector_size,
                        input_length=2*model.window,
                        trainable=learn_words,
                        #weights=[np.array([[1,2],[3,4],[5,6]],'float32')]
                        weights=[model.syn0]
                        )
    kerasmodel.add_node(
        # Embedding(vocab_size, vector_size,
        #           input_length=2,
        #           trainable=learn_words,
        #           #weights=[np.array([[1,2],[3,4],[5,6]],'float32')]
        #           ),
        embedword,
        name='embedword', input='iword')

    embedindex=Embedding(index_size, vector_size,
                         input_length=1,
                         trainable=learn_doctags,
                         #weights=[np.array([[10,20],[30,40]],'float32')]
                         weights=[model.docvecs.doctag_syn0]
                         )
    kerasmodel.add_node(
        # Embedding(index_size, vector_size,
        #           input_length=1,
        #           trainable=learn_doctags,
        #           #weights=[np.array([[10,20],[30,40]],'float32')]
        #           ),
        embedindex,
        name='embedindex', input='index')


    kerasmodel.add_node(Flatten(),name='embedconcat',inputs=['embedindex','embedword'],merge_mode='concat', concat_axis=1)

    if model.hs:
        hidden=Dense(code_dim, activation='sigmoid',b_constraint = keras.constraints.maxnorm(0),
                     trainable=learn_hidden,
                     weights=[model.syn1.T,np.zeros((code_dim))]
                     )
    else:
        hidden=Dense(code_dim, activation='sigmoid',b_constraint = keras.constraints.maxnorm(0),
                     trainable=learn_hidden,
                     weights=[model.syn1neg.T,np.zeros((code_dim))]
                     )
        
    
    # hidden=Dense(code_dim, activation='sigmoid',b_constraint = keras.constraints.maxnorm(0),
    #                           trainable=learn_hidden
    #                           )
    
    kerasmodel.add_node(
        # Dense(code_dim, activation='sigmoid', #b_constraint = keras.constraints.maxnorm(0),
        #       #input_dim=(6,),
        #       trainable=learn_hidden
        #       )
        hidden
        , name='sigmoid',
        input='embedconcat'
        #inputs=['flattenindex','flattenword'],merge_mode='concat'

        )

    kerasmodel.add_input(name='point', input_shape=(code_dim,), dtype=REAL)
    kerasmodel.add_node(kerasmodel.inputs['point'],name='pointnode')


    kerasmodel.add_output(name='code',inputs=['sigmoid','pointnode'], merge_mode='mul')

    kerasmodel.compile('rmsprop', {'code':'mse'})
    #print kerasmodel.predict({'index':np.array([[0],[1]]),'iword':np.array([[1,0],[1,1]]),'point':np.array([[1,1],[1,1]] )  }) 
    return kerasmodel
        
class Doc2VecKeras(gensim.models.doc2vec.Doc2Vec):

    def train(self, docs=None, chunksize=800,learn_doctags=True, learn_words=True, learn_hidden=True,iter=None):
        if iter!=None:
            self.iter=iter
        if docs==None:
            docs=self.docvecs
        print 'Doc2VecKeras.train sg=',self.sg
        vocab_size=len(self.vocab)
        index_size=len(self.docvecs)

        batch_size=800 ##optimized 1G mem video card
        #batch_size=3200
        batch_size=3
        samples_per_epoch=int(self.window*2*sum(map(len,docs)))
        #print 'samples_per_epoch',samples_per_epoch
        if self.sg:
            #print'Doc2VecKeras',self.sg
            #self.build_keras_model()
            self.kerasmodel=build_keras_model_dbow(index_size=index_size,vector_size=self.vector_size,vocab_size=vocab_size,code_dim=vocab_size,model=self,learn_doctags=learn_doctags, learn_words=learn_words, learn_hidden=learn_hidden)
            # gen=train_batch_dbow(self, docs, self.alpha, batch_size=batch_size)
            # print gen
            # for g in gen:
            #     print g
            # sys.exit()
            self.kerasmodel.fit_generator(
                train_batch_dbow(self, docs, self.alpha, batch_size=batch_size),
                samples_per_epoch=samples_per_epoch, nb_epoch=self.iter)

            self.docvecs.doctag_syn0=self.kerasmodel.nodes['embedding'].get_weights()[0]
           
             #self.syn0=self.kerasmodel.nodes['embedding'].get_weights()[0]
        # elif self.dm_concat:
        #     tally += train_document_dm_concat(self, doc.words, doctag_indexes, alpha, work, neu1,
        #                                           doctag_vectors=doctag_vectors, doctag_locks=doctag_locks)
        else:
            if self.dm_concat:
                self.kerasmodel=build_keras_model_dm_concat(index_size,self.vector_size,vocab_size,vocab_size, model=self,learn_doctags=learn_doctags, learn_words=learn_words, learn_hidden=learn_hidden)
                
                # count=0
                # #for w in train_document_dm_concat_xy_generator(self, docs):
                # for w in train_document_dm_concat(self, docs,batch_size):
                #     print w
                #     count +=1
                #     if count > 1 :
                #         break

                # sys.exit()

                self.kerasmodel.fit_generator(
                    train_document_dm_concat(self, docs, batch_size=batch_size),
                    samples_per_epoch=samples_per_epoch, nb_epoch=self.iter)

                #tally += train_document_dm(self, doc.words, doctag_indexes, alpha, work, neu1,
                self.docvecs.doctag_syn0=self.kerasmodel.nodes['embedindex'].get_weights()[0] 
                self.syn0=self.kerasmodel.nodes['embedword'].get_weights()[0]
                
            else:
                #print'Doc2VecKeras',self.sg

                self.kerasmodel=build_keras_model_dm(index_size,self.vector_size,vocab_size,vocab_size, model=self,learn_doctags=learn_doctags, learn_words=learn_words, learn_hidden=learn_hidden)

                # count=0
                # for w in train_batch_dm(self, docs,batch_size):
                #     print w
                #     count +=1
                #     if count > 2 :
                #         break

                # sys.exit()

                # sys.exit()
                self.kerasmodel.fit_generator(
                    train_batch_dm(self, docs, batch_size=batch_size),
                    samples_per_epoch=samples_per_epoch, nb_epoch=self.iter)

                #tally += train_document_dm(self, doc.words, doctag_indexes, alpha, work, neu1,
                self.docvecs.doctag_syn0=self.kerasmodel.nodes['embedindex'].get_weights()[0] 
                self.syn0=self.kerasmodel.nodes['embedword'].get_weights()[0]

                
    #def train_with_word2vec_instance(self,docs,w2v,learn_words=False, **kwargs):
    def train_with_word2vec_instance(self,docs,w2v, **kwargs):        
        self.sg = w2v.sg
        self.window = w2v.window 
        self.min_count =w2v.min_count
        self.sample =w2v.sample
        
        self.negative = w2v.negative
        self.hs=w2v.hs
            
        self.alpha = w2v.alpha 
        
        if w2v.hs:
            self.syn1=w2v.syn1
        else:
            self.syn1neg=w2v.syn1neg
            self.cum_table=w2v.cum_table

        self.layer1_size= w2v.layer1_size
        self.vector_size=w2v.vector_size

        #self.sorted_vocab = w2v.sorted_vocab
        self.raw_vocab=w2v.raw_vocab
        self.vocab=w2v.vocab
        self.index2word=w2v.index2word
        self.max_vocab_size = w2v.max_vocab_size
        self.build_vocab(docs)
        self.syn0=w2v.syn0
        self.train(docs,**kwargs)
        #self.train(docs,learn_words=learn_words,**kwargs)
        

class LabeledListSentence(object):
    def __init__(self, words_list):
        """
        words_list like:
        words_list = [
        ['human', 'interface', 'computer'],
        ['survey', 'user', 'computer', 'system', 'response', 'time'],
        ['eps', 'user', 'interface', 'system'],
        ]
        sentence = LabeledListSentence(words_list)
        """
        self.words_list = words_list
    
    def __getitem__(self, index):
        t = [t for t in self]
        return t[index]
    def __iter__(self):
        for i, words in enumerate(self.words_list):
            #yield LabeledSentence(words, ['SENT_{0}'.format(i)])
            yield gensim.models.doc2vec.TaggedDocument(words, [i])


if __name__ == "__main__":
    
    #kerasmodel=build_keras_model_dm(index_size=2,vector_size=2,vocab_size=3,code_dim=2)
    #kerasmodel=build_keras_model_dm_concat(index_size=2,vector_size=2,vocab_size=3,code_dim=2)
    #print kerasmodel.predict({'index':np.array([[0],[1]]),'iword':np.array([[1,0],[1,1]]),'point':np.array([[1,1],[1,1]] )  })
    #sys.exit()
    
    input_file = 'test.txt'
    doc1=gensim.models.doc2vec.TaggedLineDocument(input_file)
    #print doc1
    
    #print len(doc1)
    #print doc1.count
    
    ###debug print
    # print doc1
    # for d in doc1:
    #     print d
    #print doc1.tags
    #print doc1[0]
    
    # dvdbowk1=Doc2VecKeras(doc1,size=10,dm=0,iter=3)    
    # print(dvdbowk1.docvecs.most_similar(0))
    # dvdbow1=gensim.models.doc2vec.Doc2Vec(doc1,size=10,dm=0)
    # print(dvdbow1.docvecs.most_similar(0))
    # print dvdbowk1.docvecs[0]
    # print dvdbow1.docvecs[0]
    
    # # # sys.exit()
    
    # #dvdmk1=Doc2VecKeras(doc1,size=10,dm=1)
    # dvdmk1=Doc2VecKeras(doc1,dm=1)
    # dvdm1=gensim.models.doc2vec.Doc2Vec(doc1,dm=1,iter=3)
    # print(dvdmk1.docvecs.most_similar(0))
    # print(dvdm1.docvecs.most_similar(0))    


    # #dvdmk1=Doc2VecKeras(doc1,size=5,dm=1,dm_concat=1,window=3)
    # dvdmck1=Doc2VecKeras(doc1,dm=1,dm_concat=1,iter=10)
    # dvdmc1=gensim.models.doc2vec.Doc2Vec(doc1,dm=1,dm_concat=1,iter=3)
    # print(dvdmck1.docvecs.most_similar(0))
    # print(dvdmc1.docvecs.most_similar(0))

    # sys.exit()

    from word2veckeras import Word2VecKeras
    vk = Word2VecKeras(gensim.models.word2vec.LineSentence(input_file),iter=3)
    dk=Doc2VecKeras()
    #dk=Doc2VecKeras(doc1)
    #dk=Doc2VecKeras(vk)
    #dk.build_vocab(vk)
    dk.import_from_word2vec_instance(vk)
    #dk.build_vocab(doc1)
    dk.scan_vocab(doc1)
    dk.train(doc1,learn_words=False)
    
    sys.exit()
    
    from nltk.corpus import brown #, movie_reviews, treebank
    # print(brown.sents()[0])

    dvb=gensim.models.doc2vec.Doc2Vec(LabeledListSentence(brown.sents()),dm=0)
    print(dvb.docvecs.most_similar(0))
    dvbk=Doc2VecKeras(LabeledListSentence(brown.sents()),dm=0)
    print(dvbk.docvecs.most_similar(0))
    # br = gensim.models.word2vec.Word2Vec(brown.sents())
    # brk = Word2VecKeras(brown.sents(),iter=10)

    dvb=gensim.models.doc2vec.Doc2Vec(LabeledListSentence(brown.sents()),dm=1)
    print(dvb.docvecs.most_similar(0))
    dvbk=Doc2VecKeras(LabeledListSentence(brown.sents()),dm=1)
    print(dvbk.docvecs.most_similar(0))



    
