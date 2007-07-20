# Natural Language Toolkit: Maximum Entropy Classifiers
#
# Copyright (C) 2007 University of Pennsylvania
# Author: Edward Loper <edloper@gradient.cis.upenn.edu>
# URL: <http://nltk.sf.net>
# For license information, see LICENSE.TXT
#
# $Id: naivebayes.py 2063 2004-07-17 21:02:24Z edloper $

"""
A classifier model based on maximum entropy modeling framework.  This
framework considers all of the probability distributions that are
emperically consistant with the training data; and chooses the
distribution with the highest entropy.  A probability distribution is
X{emperically consistant} with a set of training data if its estimated
frequency with which a class and a feature vector value co-occur is
equal to the actual frequency in the data.
"""

from nltk.classify.api import *
from nltk.classify.util import *
from nltk.probability import *
from nltk import defaultdict
import numpy, time

######################################################################
#{ Classifier Model
######################################################################

class ConditionalExponentialClassifier(ClassifyI):
    def __init__(self, labels, encoding, weights):
        """
        Construct a new conditional exponential classifier model.
        Typically, new classifier models are created by
        C{ClassifierTrainer}s.

        @type labels: C{list}
        @param labels: A list of the labels that can be generated by
            this classifier.  The order of these labels must
            correspond to the order of the weights.
        @type weights: C{list} of C{float}
        @param weights:  The feature weight vector for this classifier.
            Weight M{w[i,j]} is encoded by C{weights[i+j*N]}, where
            C{N} is the length of the feature vector.
        """
        self._encoding = encoding
        self._labels = labels # <- order matters here!
        self._weights = weights
        assert encoding.length() * len(labels) == len(weights)

    def labels(self):
        return self._labels

    def set_weights(self, new_weights):
        """
        Set the feature weight vector for this classifier.  Weight
        M{w[i,j]} is encoded by C{weights[i+j*N]}, where C{N} is the
        length of the feature vector.
        @param new_weights: The new feature weight vector.
        @type new_weights: C{list} of C{float}
        """
        self._weights = new_weights
        assert (self._encoding.length() * len(self._labels) ==
                len(new_weights))

    def weights(self):
        """
        @return: The feature weight vector for this classifier.
        Weight M{w[i,j]} is encoded by C{weights[i+j*N]}, where C{N}
        is the length of the feature vector.
        @rtype new_weights: C{list} of C{float}
        """
        return self._weights

    def classify(self, featureset):
        if isinstance(featureset, list): # Handle batch mode.
            return [self.classify(fs) for fs in featureset]
        
        return self.probdist(featureset).max()
        
    def probdist(self, featureset):
        if isinstance(featureset, list): # Handle batch mode.
            return [self.probdist(fs) for fs in featureset]
        
        feature_vector = self._encoding.encode(featureset)
            
        prob_dict = {}
        for i, label in enumerate(self._labels):
            # Find the offset into the weights vector.
            offset = i * self._encoding.length()

            # Multiply the weights of all active features for this class.
            prod = 1.0
            for (id, val) in feature_vector:
                prod *= (self._weights[id+offset] ** val)
            prob_dict[label] = prod

        # Normalize the dictionary to give a probability distribution
        return DictionaryProbDist(prob_dict, normalize=True)
        
    def __repr__(self):
        return ('<ConditionalExponentialClassifier: %d labels, %d features>' %
                (len(self._labels), self._encoding.length()))

######################################################################
#{ Classifier Trainer: Generalized Iterative Scaling
######################################################################

def gis(train_toks, ll_cutoff=None, lldelta_cutoff=None,
        acc_cutoff=None, accdelta_cutoff=None, debug=3,
        iterations=10):
    """
    Train a maximum entropy classifier for the given training data,
    using the generalized iterative scaling algorithm.
    """
    # Find a list of all labels in the training data.
    labels = attested_labels(train_toks)

    # Construct an encoding from the training data.
    encoding = GISEncoding.train(train_toks)

    # Cinv is the inverse of the sum of each vector.  This controls
    # the learning rate: higher Cinv (or lower C) gives faster
    # learning.
    Cinv = 1.0/encoding.C()
    
    # Build the offsets dictionary.  This maps from a class to the
    # index in the weight vector where that class's weights begin.
    offsets = dict([(label, i*encoding.length())
                    for i, label in enumerate(labels)])

    # Count how many times each feature occurs in the training data.
    emperical_fcount = calculate_emperical_fcount(train_toks, encoding,
                                                  offsets)
    
    # Define an array that is 1 whenever emperical_fcount is zero.  In
    # other words, it is one for any feature that's not attested in
    # the training data.  This is used to avoid division by zero.
    unattested = numpy.zeros(len(emperical_fcount))
    for i in range(len(emperical_fcount)):
        if emperical_fcount[i] == 0: unattested[i] = 1

    # Build the classifier.  Start with weight=1 for each feature,
    # except for the unattested features.  Start those out at
    # zero, since we know that's the correct value.
    weights = numpy.ones(len(emperical_fcount), 'd')
    weights -= unattested
    classifier = ConditionalExponentialClassifier(labels, encoding, weights)

    # Old log-likelihood and accuracy; used to check if the change
    # in log-likelihood or accuracy is sufficient to indicate convergence.
    ll_old = None
    acc_old = None
        
    if debug > 0: print '  ==> Training (%d iterations)' % iterations
    if debug > 2:
        print
        print '      Iteration    Log Likelihood    Accuracy'
        print '      ---------------------------------------'

    # Train for a fixed number of iterations.!
    for iternum in range(iterations):
        if debug > 2:
            ll = classifier_log_likelihood(classifier, train_toks)
            acc = classifier_accuracy(classifier, train_toks)
            print '     %9d    %14.5f    %9.3f' % (iternum+1, ll, acc)
        
        # Use the model to estimate the number of times each
        # feature should occur in the training data.
        estimated_fcount = calculate_estimated_fcount(classifier, train_toks,
                                                      encoding, offsets)

        # Avoid division by zero.
        estimated_fcount += unattested
        
        # Update the classifier weights
        weights = classifier.weights()
        weights *= (emperical_fcount / estimated_fcount) ** Cinv
        classifier.set_weights(weights)

        # Check log-likelihood cutoffs.
        if ll_cutoff is not None or lldelta_cutoff is not None:
            ll = classifier_log_likelihood(classifier, train_toks)
            if ll_cutoff is not None and ll >= -abs(ll_cutoff): break
            if lldelta_cutoff is not None:
                if ll_old and (ll - ll_old) <= lldelta_cutoff: break
                ll_old = ll

        # Check accuracy cutoffs.
        if acc_cutoff is not None or accdelta_cutoff is not None:
            acc = classifier_accuracy(classifier, train_toks)
            if acc_cutoff is not None and acc >= acc_cutoff: break
            if accdelta_cutoff is not None:
                if acc_old and (acc_old - acc) <= accdelta_cutoff: break
                acc_old = acc

    if debug > 2:
        ll = classifier_log_likelihood(classifier, train_toks)
        acc = classifier_accuracy(classifier, train_toks)
        print '         Final    %14.5f    %9.3f' % (ll, acc)

    # Return the classifier.
    return classifier

def calculate_emperical_fcount(train_toks, encoding, offsets):
    fcount = numpy.zeros(encoding.length()*len(offsets), 'd')

    for tok, label in train_toks:
        offset = offsets[label]
        for (index, val) in encoding.encode(tok):
            fcount[index+offset] += val

    return fcount

def calculate_estimated_fcount(classifier, train_toks, encoding, offsets):
    fcount = numpy.zeros(encoding.length()*len(offsets), 'd')

    for tok, label in train_toks:
        pdist = classifier.probdist(tok)
        for label, offset in offsets.items():
            prob = pdist.prob(label)
            for (index, val) in encoding.encode(tok):
                fcount[index+offset] += prob*val

    return fcount


######################################################################
#{ Classifier Trainer: Improved Iterative Scaling
######################################################################

def iis(train_toks, **kwargs):
    """
    Train a new C{ConditionalExponentialClassifier}, using the given
    training samples.  This C{ConditionalExponentialClassifier} should
    encode the model that maximizes entropy from all the models that
    are emperically consistant with C{train_toks}.
    
    @param kwargs: Keyword arguments.
      - C{iterations}: The maximum number of times IIS should
        iterate.  If IIS converges before this number of
        iterations, it may terminate.  Default=C{20}.
        (type=C{int})
        
      - C{debug}: The debugging level.  Higher values will cause
        more verbose output.  Default=C{0}.  (type=C{int})
        
      - C{labels}: The set of possible labels.  If none is given,
        then the set of all labels attested in the training data
        will be used instead.  (type=C{list} of (immutable)).
        
      - C{accuracy_cutoff}: The accuracy value that indicates
        convergence.  If the accuracy becomes closer to one
        than the specified value, then IIS will terminate.  The
        default value is None, which indicates that no accuracy
        cutoff should be used. (type=C{float})

      - C{delta_accuracy_cutoff}: The change in accuracy should be
        taken to indicate convergence.  If the accuracy changes by
        less than this value in a single iteration, then IIS will
        terminate.  The default value is C{None}, which indicates
        that no accuracy-change cutoff should be
        used. (type=C{float})

      - C{log_likelihood_cutoff}: specifies what log-likelihood
        value should be taken to indicate convergence.  If the
        log-likelihod becomes closer to zero than the specified
        value, then IIS will terminate.  The default value is
        C{None}, which indicates that no log-likelihood cutoff
        should be used. (type=C{float})

      - C{delta_log_likelihood_cutoff}: specifies what change in
        log-likelihood should be taken to indicate convergence.
        If the log-likelihood changes by less than this value in a
        single iteration, then IIS will terminate.  The default
        value is C{None}, which indicates that no
        log-likelihood-change cutoff should be used.  (type=C{float})
    """
    # Process the keyword arguments.
    iterations = 10
    debug = 3
    labels = None
    ll_cutoff = lldelta_cutoff = None
    acc_cutoff = accdelta_cutoff = None
    for (key, val) in kwargs.items():
        if key in ('iterations', 'iter'): iterations = val
        elif key == 'debug': debug = val
        elif key == 'labels': labels = val
        elif key == 'log_likelihood_cutoff':
            ll_cutoff = abs(val)
        elif key == 'delta_log_likelihood_cutoff':
            lldelta_cutoff = abs(val)
        elif key == 'accuracy_cutoff': 
            acc_cutoff = abs(val)
        elif key == 'delta_accuracy_cutoff':
            accdelta_cutoff = abs(val)
        else: raise TypeError('Unknown keyword arg %s' % key)
    if labels is None:
        labels = attested_labels(train_toks)
        
    # Find a list of all labels in the training data.
    labels = attested_labels(train_toks)

    # Construct an encoding from the training data.
    encoding = SparseBinaryVectorEncoding.train(train_toks)
    
    # Build the offsets dictionary.  This maps from a class to the
    # index in the weight vector where that class's weights begin.
    offsets = dict([(label, i*encoding.length())
                    for i, label in enumerate(labels)])

    # Count how many times each feature occurs in the training data.
    emperical_ffreq = calculate_emperical_fcount(train_toks, encoding,
                                                 offsets) / len(train_toks)

    # Find the nf map, and related variables nfarray and nfident.
    # nf is the sum of the features for a given labeled text.
    # nfmap compresses this sparse set of values to a dense list.
    # nfarray performs the reverse operation.  nfident is 
    # nfarray multiplied by an identity matrix.
    nfmap = calculate_nfmap(train_toks, encoding)
    nfarray = numpy.array(sorted(nfmap, key=nfmap.__getitem__), 'd')
    nftranspose = numpy.reshape(nfarray, (len(nfarray), 1))

    # An array that is 1 whenever emperical_ffreq is zero.  In
    # other words, it is one for any feature that's not attested
    # in the data.  This is used to avoid division by zero.
    unattested = numpy.zeros(len(emperical_ffreq))
    for i in range(len(emperical_ffreq)):
        if emperical_ffreq[i] == 0: unattested[i] = 1

    # Build the classifier.  Start with weight=1 for each feature,
    # except for the unattested features.  Start those out at
    # zero, since we know that's the correct value.
    weights = numpy.ones(len(emperical_ffreq), 'd')
    weights -= unattested
    classifier = ConditionalExponentialClassifier(labels, encoding, weights)
            
    if debug > 0: print '  ==> Training (%d iterations)' % iterations
    if debug > 2:
        print
        print '      Iteration    Log Likelihood    Accuracy'
        print '      ---------------------------------------'

    # Train for a fixed number of iterations.
    for iternum in range(iterations):
        if debug > 2:
            ll = classifier_log_likelihood(classifier, train_toks)
            acc = classifier_accuracy(classifier, train_toks)
            print '     %9d    %14.5f    %9.3f' % (iternum+1, ll, acc)

        # Calculate the deltas for this iteration, using Newton's method.
        deltas = calculate_deltas(
            train_toks, classifier, unattested, emperical_ffreq, 
            nfmap, nfarray, nftranspose, offsets, encoding)

        # Use the deltas to update our weights.
        weights = classifier.weights()
        weights *= 2**deltas # numpy.exp(deltas)
        classifier.set_weights(weights)
                    
        # Check log-likelihood cutoffs.
        if ll_cutoff is not None or lldelta_cutoff is not None:
            ll = classifier_log_likelihood(classifier, train_toks)
            if ll_cutoff is not None and ll > -ll_cutoff: break
            if lldelta_cutoff is not None:
                if (ll - ll_old) < lldelta_cutoff: break
                ll_old = ll

        # Check accuracy cutoffs.
        if acc_cutoff is not None or accdelta_cutoff is not None:
            acc = classifier_accuracy(classifier, train_toks)
            if acc_cutoff is not None and acc < acc_cutoff: break
            if accdelta_cutoff is not None:
                if (acc_old - acc) < accdelta_cutoff: break
                acc_old = acc

    if debug > 2:
        ll = classifier_log_likelihood(classifier, train_toks)
        acc = classifier_accuracy(classifier, train_toks)
        print '         Final    %14.5f    %9.3f' % (ll, acc)
               
    # Return the classifier.
    return classifier

def calculate_nfmap(train_toks, encoding):
    """
    Construct a map that can be used to compress C{nf} (which is
    typically sparse).

    M{nf(t)} is the sum of the feature values for M{t}::

        nf(t) = sum(fv(t))

    This represents the number of features that are active for a
    given labeled text.  This method finds all values of M{nf(t)}
    that are attested for at least one token in the given list of
    training tokens; and constructs a dictionary mapping these
    attested values to a continuous range M{0...N}.  For example,
    if the only values of M{nf()} that were attested were 3, 5,
    and 7, then C{_nfmap} might return the dictionary {3:0, 5:1,
    7:2}.

    @return: A map that can be used to compress C{nf} to a dense
        vector.
    @rtype: C{dictionary} from C{int} to C{int}
    """
    # Map from nf to indices.  This allows us to use smaller arrays.
    nfset = set()
    for tok, label in train_toks:
        nfset.add(sum([val for (id,val) in encoding.encode(tok)]))
    return dict([(nf, i) for (i, nf) in enumerate(nfset)])

def calculate_deltas(train_toks, classifier, unattested, ffreq_emperical,
                     nfmap, nfarray, nftranspose, offsets, encoding):
    """
    Calculate the update values for the classifier weights for
    this iteration of IIS.  These update weights are the value of
    C{delta} that solves the equation::
    
      ffreq_emperical[i]
             =
      SUM[t,l] (classifier.prob(LabeledText(t,l)) *
                fd_list.detect(LabeledText(t,l))[i] *
                exp(delta[i] * nf(LabeledText(t,l))))

    Where:
        - M{t} is a text C{labeled_tokens}
        - M{l} is an element of C{labels}
        - M{nf(ltext)} = SUM[M{j}] C{fd_list.detect}(M{ltext})[M{j}] 

    This method uses Newton's method to solve this equation for
    M{delta[i]}.  In particular, it starts with a guess of
    C{delta[i]}=1; and iteratively updates C{delta} with::

        delta[i] -= (ffreq_emperical[i] - sum1[i])/(-sum2[i])

    until convergence, where M{sum1} and M{sum2} are defined as::
    
      sum1 = SUM[t,l] (classifier.prob(LabeledText(t,l)) *
                       fd_list.detect(LabeledText(t,l))[i] *
                       exp(delta[i] * nf(LabeledText(t,l))))
      sum2 = SUM[t,l] (classifier.prob(LabeledText(t,l)) *
                       fd_list.detect(LabeledText(t,l))[i] *
                       nf(LabeledText(t,l)) *
                       exp(delta[i] * nf(LabeledText(t,l))))

    Note that M{sum1} and M{sum2} depend on C{delta}; so they need
    to be re-computed each iteration.
    
    The variables C{nfmap}, C{nfarray}, and C{nftranspose} are
    used to generate a dense encoding for M{nf(ltext)}.  This
    allows C{_deltas} to calculate M{sum1} and M{sum2} using
    matrices, which yields a signifigant performance improvement. 

    @param fd_list: The feature detector list for the classifier
        that this C{IISMaxentClassifierTrainer} is training.
    @type fd_list: C{FeatureDetectorListI}
    @param labeled_tokens: The set of training tokens.
    @type labeled_tokens: C{list} of C{Token} with C{LabeledText}
        type
    @param labels: The set of labels that should be considered by
        the classifier constructed by this
        C{IISMaxentClassifierTrainer}. 
    @type labels: C{list} of (immutable)
    @param classifier: The current classifier.
    @type classifier: C{ClassifierI}
    @param ffreq_emperical: An array containing the emperical
        frequency for each feature.  The M{i}th element of this
        array is the emperical frequency for feature M{i}.
    @type ffreq_emperical: C{sequence} of C{float}
    @param unattested: An array that is 1 for features that are
        not attested in the training data; and 0 for features that
        are attested.  In other words, C{unattested[i]==0} iff
        C{ffreq_emperical[i]==0}. 
    @type unattested: C{sequence} of C{int}
    @param nfmap: A map that can be used to compress C{nf} to a dense
        vector.
    @type nfmap: C{dictionary} from C{int} to C{int}
    @param nfarray: An array that can be used to uncompress C{nf}
        from a dense vector.
    @type nfarray: C{array} of C{float}
    @param nftranspose: C{array} of C{float}
    @type nftranspose: The transpose of C{nfarray}
    """
    # These parameters control when we decide that we've
    # converged.  It probably should be possible to set these
    # manually, via keyword arguments to train.
    NEWTON_CONVERGE = 1e-12
    MAX_NEWTON = 300
    
    deltas = numpy.ones(encoding.length()*len(offsets), 'd')

    # Precompute the A matrix:
    # A[nf][id] = sum ( p(text) * p(label|text) * f(text,label) )
    # over all label,text s.t. num_features[label,text]=nf
    A = numpy.zeros((len(nfmap), encoding.length()*len(offsets)), 'd')

    for tok, label in train_toks:
        dist = classifier.probdist(tok)

        # Find the number of active features.
        feature_vector = encoding.encode(tok)
        nf = sum([val for (id, val) in feature_vector])

        # Update the A matrix
        for label, offset in offsets.items():
            for (id, val) in feature_vector:
                A[nfmap[nf], id+offset] += dist.prob(label) * val
    A /= len(train_toks)

    # Iteratively solve for delta.  Use the following variables:
    #   - nf_delta[x][y] = nfarray[x] * delta[y]
    #   - exp_nf_delta[x][y] = exp(nf[x] * delta[y])
    #   - nf_exp_nf_delta[x][y] = nf[x] * exp(nf[x] * delta[y])
    #   - sum1[i][nf] = sum p(text)p(label|text)f[i](label,text)
    #                       exp(delta[i]nf)
    #   - sum2[i][nf] = sum p(text)p(label|text)f[i](label,text)
    #                       nf exp(delta[i]nf)
    for rangenum in range(MAX_NEWTON):
        nf_delta = numpy.outer(nfarray, deltas)
        exp_nf_delta = 2 ** nf_delta
        nf_exp_nf_delta = nftranspose * exp_nf_delta
        sum1 = numpy.sum(exp_nf_delta * A, axis=0)
        sum2 = numpy.sum(nf_exp_nf_delta * A, axis=0)

        # Avoid division by zero.
        sum2 += unattested

        # Update the deltas.
        deltas -= (ffreq_emperical - sum1) / -sum2

        # We can stop once we converge.
        n_error = (numpy.sum(abs((ffreq_emperical-sum1)))/
                   numpy.sum(abs(deltas)))
        if n_error < NEWTON_CONVERGE:
            return deltas

    return deltas

######################################################################
#{ Demo
######################################################################
def demo():
    from nltk.classify.util import names_demo
    print 'Generalized Iterative Scaling:'
    classifier = names_demo(gis)
    print 'Improved Iterative Scaling:'
    classifier = names_demo(iis)

if __name__ == '__main__':
    demo()