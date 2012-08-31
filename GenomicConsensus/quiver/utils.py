import numpy as np, itertools, logging
from GenomicConsensus.variants import *
import ConsensusCore as cc

# Some lisp functions we want
fst   = lambda t: t[0]
snd   = lambda t: t[1]
third = lambda t: t[2]

def uniqueSingleBaseMutations(templateSequence, positions=None):
    """
    Return an iterator over all single-base mutations of a
    templateSequence that result in unique mutated sequences.
    """
    allBases = "ACGT"
    prevTplBase = None
    positions = positions or xrange(0, len(templateSequence))
    for tplStart in positions:
        tplBase = templateSequence[tplStart]
        # snvs
        for subsBase in allBases:
            if subsBase != tplBase:
                yield cc.Mutation(cc.SUBSTITUTION, tplStart, subsBase)
        # Insertions---only allowing insertions that are not cognate
        # with the previous base.
        for insBase in allBases:
            if insBase != prevTplBase:
                yield cc.Mutation(cc.INSERTION, tplStart, insBase)
        # Deletion--only allowed if refBase does not match previous tpl base
        if tplBase != prevTplBase:
            yield cc.Mutation(cc.DELETION, tplStart, "-")
        prevTplBase = tplBase

def nearbyMutations(mutations, tpl, neighborhoodSize):
    """
    Return mutations nearby the previously-tried mutations
    """
    mutationPositions = map(cc.Mutation.Position, mutations)
    nearbyPositions = set()
    for mp in mutationPositions:
        nearbyPositions.update(range(max(0, mp - neighborhoodSize),
                                     min(len(tpl), mp + neighborhoodSize)))
    return uniqueSingleBaseMutations(tpl, sorted(nearbyPositions))

def asFloatFeature(arr):
    return cc.FloatFeature(np.array(arr, dtype=np.float32))

def bestSubset(mutationsAndScores, separation):
    """
    Given a list of (mutation, score) tuples, this utility method
    greedily chooses the highest scoring well-separated elements.  We
    use this to avoid applying adjacent high scoring mutations, which
    are the rule, not the exception.  We only apply the best scoring one
    in each neighborhood, and then revisit the neighborhoods after
    applying the mutations.
    """
    input = mutationsAndScores[:]
    output = []

    while input:
        best = max(input, key=snd)
        output.append(best)
        nStart = best[0].Position() - separation
        nEnd   = best[0].Position() + separation
        for t in input[:]:
            if nStart <= t[0].Position() <= nEnd:
                input.remove(t)

    return output

def refineConsensus(mms, maxRounds=10, verbose=False):
    #
    # Given a MultiReadMutationScorer, identify and apply favorable
    # template mutations.  Return the consensus string.
    #
    SEPARATION = 7
    NEIGHBORHOOD = 15
    favorableMutationsAndScores = None

    for round in range(1, maxRounds):

        if favorableMutationsAndScores == None:
            mutationsToTry = uniqueSingleBaseMutations(mms.Template())
        else:
            favorableMutations = map(fst, favorableMutationsAndScores)
            mutationsToTry = nearbyMutations(favorableMutations, mms.Template(), NEIGHBORHOOD)

        favorableMutationsAndScores = \
            [(m, mms.Score(m)) for m in
             filter(mms.FastIsFavorable, mutationsToTry)]

        if favorableMutationsAndScores:
            bestMutations = map(fst,
                                bestSubset(favorableMutationsAndScores, SEPARATION))
            mms.ApplyMutations(bestMutations)
        else:
            # If we can't find any favorable mutations, our work is done.
            break
    logging.debug("Quiver: %d rounds" % round)
    return mms.Template()

def inverseMutations(windowStart, variant):
    """
    Given a (potentially multibase) variant, return the list of single
    base mutations that 'undo' the variant.
    """
    start = variant.refStart - windowStart
    length = len(variant)
    if isinstance(variant, Insertion):
        ms = [cc.Mutation(cc.DELETION, pos, "-")
              for pos in xrange(start, start+length)]
    elif isinstance(variant, Deletion):
        ms = [cc.Mutation(cc.INSERTION, start, base)
              for base in variant.refSequence]
    elif isinstance(variant, Substitution):
        ms = [cc.Mutation(cc.SUBSTITUTION, pos, base)
              for (pos, base) in zip(range(start, start+length),
                                     variant.refSequence)]
    else:
        raise Exception, "Should not reach here"
    return ms

def variantsFromAlignment(a, refWindow):
    """
    Extract the variants implied by a pairwise alignment to the
    reference.
    """
    variants = []
    refId, refStart, _ = refWindow
    refPos = refStart
    tbl = zip(a.Transcript(),
              a.Target(),
              a.Query())
    runs = itertools.groupby(tbl, fst)
    for code, run in runs:
        assert code in "RIDM"
        run = list(run)
        ref = "".join(map(snd, run))
        read = "".join(map(third, run))
        if code == "M":
            refPos += len(ref)
        elif code == "R":
            assert len(read)==len(ref)
            variants.append(Substitution(refId, refPos, refPos+len(read), ref, read))
        elif code == "I":
            variants.append(Insertion(refId, refPos, refPos, "", read))
        elif code == "D":
            variants.append(Deletion(refId, refPos, refPos + len(ref), ref, ""))
            refPos += len(ref)
    return variants

def referenceSpanWithinWindow(referenceWindow, aln):
    """
    Helper function for sorting reads by their reference span
    after restriction to a window.
    """
    _, winStart, winEnd = referenceWindow
    return min(winEnd, aln.referenceEnd) - \
           max(winStart, aln.referenceStart)


