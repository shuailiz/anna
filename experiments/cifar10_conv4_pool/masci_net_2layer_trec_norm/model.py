import numpy

import theano
import theano.tensor as T  #TODO(tpaine) remove this dependency, can be done by factoring out the cost theano equation

from fastor.layers import layers, cc_layers

theano.config.floatX = 'float32'

class Model(object):
    batch = 128
    input = cc_layers.CudaConvnetInput2DLayer(batch, 3, 32, 32)    
    y = T.lvector(name='labels')
    # k = float(numpy.random.rand()*1+0.2)
    k = 0.2
    print '## k = %.3f' % k
    winit1 = k/numpy.sqrt(5*5*3) # was = 0.25 
    winit2 = k/numpy.sqrt(5*5*96) # was = 0.75
    winit3 = k/numpy.sqrt(5*5*144)    
    winitD2 = k/numpy.sqrt(300)
    binit = 0.0
    nonlinearity = layers.rectify

    conv1 = cc_layers.CudaConvnetConv2DNoBiasLayer(input, 
                                             n_filters=96,
                                             filter_size=5,
                                             weights_std=winit1,
                                             nonlinearity=nonlinearity,
                                             pad=1)
    pool1 = cc_layers.CudaConvnetPooling2DLayer(conv1, 2, stride=2)
    conv2 = cc_layers.CudaConvnetConv2DNoBiasLayer(pool1, 
                                             n_filters=144,
                                             filter_size=5,
                                             weights_std=winit2,
                                             nonlinearity=nonlinearity,
                                             pad=1)
    pool2 = cc_layers.CudaConvnetPooling2DLayer(conv2, 2, stride=2)
    unpool3 = cc_layers.CudaConvnetUnpooling2DLayer(pool2, pool2)
    conv3 = cc_layers.CudaConvnetDeconv2DNoBiasLayer(unpool3, conv2)        
    unpool4 = cc_layers.CudaConvnetUnpooling2DLayer(conv3, pool1)
    output = cc_layers.CudaConvnetDeconv2DNoBiasLayer(unpool4, conv1, nonlinearity=layers.identity)
    
    # Layers for Supervised Finetuning    
    pool2_shuffle = cc_layers.ShuffleC01BToBC01Layer(pool2)    
    winitD1 = k/numpy.sqrt(numpy.prod(pool2.get_output_shape()))
    fc3 = layers.DenseLayer(pool2_shuffle,
                            n_outputs = 300,
                            weights_std=winitD1,
                            init_bias_value=0.0,
                            nonlinearity=nonlinearity,
                            dropout=0.5)
    y_hat = layers.DenseLayer(fc3,
                              n_outputs=10,
                              weights_std=winitD2,
                              init_bias_value=0.0,
                              nonlinearity=layers.softmax)

    def __init__(self, name, path):
        self.name = name
        self.path = path
        # lr that worked 0.000001, cost of 48 at 900 steps
        # lr that worked 0.00001, cost of 30 at 900 steps
        self.learning_rate_symbol = theano.shared(numpy.array(0.0001, dtype=theano.config.floatX))
        
        self.all_parameters_symbol = layers.all_parameters(self._get_output_layer())
        # can switch to gen_updates_regular_momentum
        self.updates_symbol = layers.gen_updates_regular_momentum(self._get_cost_symbol(),
                                                                  self.all_parameters_symbol,
                                                                  learning_rate=self.learning_rate_symbol,
                                                                  momentum=0.9,
                                                                  weight_decay=1e-5)
        self.train_func = theano.function([self._get_input_symbol()],
                                           self._get_cost_symbol(),
                                           updates=self.updates_symbol)
        self.eval_func = theano.function([self._get_input_symbol()],
                                         self._get_cost_symbol())
        self.prediction_func = theano.function([self._get_input_symbol()],
                                          self._get_output_symbol())

        
        self.all_parameters_classify_symbol = layers.all_parameters(self._get_y_hat_layer())
        self.updates_classify_symbol = layers.gen_updates_regular_momentum(self._get_classify_cost_symbol(),
                                                                  self.all_parameters_classify_symbol,
                                                                  learning_rate=self.learning_rate_symbol,
                                                                  momentum=0.9,
                                                                  weight_decay=1e-5)
        #self.classify_func = theano.function([self._get_input_symbol(), self._get_y_symbol()],
        #                                   self._get_classify_cost_symbol(),
        #                                   updates=self.updates_classify_symbol)
        
        self.classify_func = theano.function([self._get_input_symbol(), self._get_y_symbol()],
                                           [self._get_classify_cost_symbol(), self._get_accuracy_symbol()],
                                           updates=self.updates_classify_symbol)
        
        
        self.accuracy_func = theano.function([self._get_input_symbol(), self._get_y_symbol()], 
                                              self._get_accuracy_symbol())
        
       
                    
    def _get_input_symbol(self):
        return self.input.output()
    
    def _get_output_symbol(self):
        return self.output.output()
    
    def _get_y_symbol(self):
        return self.y
    
    def _get_y_hat_symbol(self):
        return self.y_hat.output()
    
    def _get_cost_symbol(self):
        input = self._get_input_symbol()
        output = self._get_output_symbol()
        cost = T.sum((output - input) ** 2)/self.batch
        return cost
    
    def _get_classify_cost_symbol(self):
        y = self._get_y_symbol()
        y_hat = self._get_y_hat_symbol()
        cost = -T.mean(T.log(y_hat)[T.arange(y.shape[0]), y])
        return cost

    def _get_output_layer(self):
        return self.output
    
    def _get_y_hat_layer(self):
        return self.y_hat
        
    def train(self, batch):
        return self.train_func(batch)
    
    def eval(self, batch):
        return self.eval_func(batch)

    def prediction(self, batch):
        return self.prediction_func(batch)
    
    def _get_accuracy_symbol(self):
        predicted_label_symbol = T.argmax(self._get_y_hat_symbol(), axis=1)
        y = self._get_y_symbol()
        accuracy_symbol = 1.0*T.sum(T.eq(predicted_label_symbol, y))/y.shape[0]
        return accuracy_symbol
    
    def classify(self, x_batch, y_batch):
        return self.classify_func(x_batch, y_batch)
    
    def accuracy(self, x_batch, y_batch):
        return self.accuracy_func(x_batch, y_batch)
