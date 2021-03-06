#!/usr/bin/env python3
"""
Code for performing derivative free optimization when:
    * The objective function is VERY expensive to evaluate
    * Derivatives are unavailable, and too expensive to approximate with a bunch of function evaluations.
    * Parameter search space is fully discrete, with known adjacency. (Grid search is a special case of this)
    * You can't afford a full grid search (simpler codes like scipy.optimizize.brute can probably do this more efficiently) 
    * Your parameter space is not well modeled by a hypercube, i.e. subsets of your parameters live on a spherical manifold, torus, SO(3),etc... Graphs with dense samplings are a very expensive representations of high dimensional spaces, but are general enough to handle non-cartesian spaces cleanly.
"""
import numpy
import networkx
import functools

from networkx import Graph

parameterNameSeparator = ','


def _sequence_graph(parameterValues):
    '''Convert a list of values to a graph that connects adgacent values'''
    graph = Graph()
    graph.add_nodes_from(parameterValues)
    graph.add_path(parameterValues)
    assert len(graph.nodes())>0, "Generated an empty graph. Is parameterValues empty?"
    return graph

def _cycle_graph(parameterValues):
    '''Convert a list of values to a graph that connects adgacent values with wraparound'''
    graph = Graph()
    graph.add_cycle(parameterValues)
    assert len(graph.nodes())>0, "Generated an empty graph. Is parameterValues empty?"
    return graph

def _complete_graph(parameterValues):
    graph = networkx.complete_graph(len(parameterValues))
    networkx.relabel_nodes(graph,mapping=dict(zip(graph,parameterValues),copy=False))
    assert len(graph.nodes())>0, "Generated an empty graph. Is parameterValues empty?"
    return graph

def _wrap_graph_generator(f):
    # Wrap a graph generator with handling of trivial cases and names
    def f_wrapped(parameterName, parameterValues):
        assert type(parameterName) is str, "You probably need to swap argument order to (key,value_tuple)"
        l = list(parameterValues)
        assert len(l) > 0, "Empty graphs not supported!"

        # Handle trivial cases
        if len(l)==1:
            graph = Graph()
            graph.add_node(parameterValues[0])
            graph.name = parameterName
            return graph
        graph = f(parameterValues)
        graph.name = parameterName
        return graph
    return f_wrapped

cycle = _wrap_graph_generator(_cycle_graph)
cycle.__doc__='''Convert a list of values to a graph that connects adgacent values'''

sequence = _wrap_graph_generator(_sequence_graph)
sequence.__doc__='''Convert a list of values to a graph that connects adgacent values'''

complete = _wrap_graph_generator(_complete_graph)
complete.__doc__=''' Convert a list of parameter values to a graph that connects all values to each other. Appropriate for options that are like enums and have no meaningful adgacency'''


def _flatten_tuples_in_product_graph(graph):
    ''' Do one level of tuple flattening in the node names of a graph IN PLACE '''
    def flatten_tuple_one_level(t):
        assert type(t) is tuple
        assert len(t)==2
        return tuple(t[0]) + (t[1], )

    oldNodeLabels = graph.nodes()
    assert type(oldNodeLabels) is list
    assert len(oldNodeLabels)>0, 'Bug: Empty graphs not supported'
    assert type(oldNodeLabels[0]) is tuple, "Bug: Product graph contains "+str(type(oldNodeLabels[0]))+", but expected tuples!"
    if type(oldNodeLabels[0][0]) is tuple: # First node, left side
        newNodeLabels = map(flatten_tuple_one_level,oldNodeLabels)
        networkx.relabel_nodes(graph,mapping=dict(zip(oldNodeLabels,newNodeLabels)),copy=False)

def _extend_product_function_to_multiple_graphs(productFunction):
    # Product function takes two graphs and returns a graph
    def product_of_multiple_graphs(graphs):
        assert type(graphs) in (list,tuple)
        assert len(graphs)>1, 'Need at least two graphs to take a product!'
        #print(list((g.name for g in graphs))) # debugging
        assert all((g.name != '' for g in graphs))
        assert all((len(g.nodes())>0 for g in graphs)), "Empty graphs not supported!"

        def product_with_flattening(g1,g2):
            assert g1.name != ''
            assert g2.name != ''
            #print(list((g.name for g in (g1,g2)))) # debugging

            assert len(g1.nodes())>0, "Empty graphs not supported!"
            assert len(g2.nodes())>0, "Empty graphs not supported!"
            graph = productFunction(g1,g2)
            assert len(graph.nodes())>0, "Empty graphs not supported!"
            _flatten_tuples_in_product_graph(graph)
            graph.name = parameterNameSeparator.join((g.name for g in (g1,g2)))
            return graph

        graph = functools.reduce(product_with_flattening, graphs)
        #print(list((g.name for g in graphs))) # debugging

        return graph
    return product_of_multiple_graphs

cartesian_product = _extend_product_function_to_multiple_graphs(networkx.cartesian_product)
strong_product = _extend_product_function_to_multiple_graphs(networkx.strong_product)

cartesian_product.__doc__='''
    Return a product graph where neighbors differ in exactly one parameter.
    Intuitively, only allows movement along the grid axes.
    Input: an iterable of graphs
    Output: the product graph
    '''

strong_product.__doc__='''
    Graph where all parameters can be different between neighbors.
    Intuitively, allows you to move "diagonally" in the grid in addition to along the axes, or diagonal-ish.
    Input: an iterable of graphs 
    Output: the product graph
    '''

def _str(graph,point):
    ''' Pretty printer for the parameter strings stuffed in a graph.name field, and a specific point '''
    n=len(point)
    names = graph.name.split(parameterNameSeparator)
    entries = (name + '=' + str(param) for name, param in zip(names, point))
    return '\t'.join(entries)

def graph_node_to_dict(graph, node):
    '''Convenience function for converting a graph node to a dict. 
        This is useful if you need to stick use your parameter list to call a function
        using named parameters. Often the function is a class instantiator.'''
    names = graph.name.split(parameterNameSeparator)
    return dict(zip(names, node))

def best_neighbor_descent(graph, objective, seed=None):
    '''
    Starting from a seed node, move to the best neighbor until a local minimum (or plateau) is reached. This is sort of an optimized version of a beam search of width 1.

    For better performance, it is reccommended that you memoize your objective
    function, i.e. with @functools.lru_cache(maxsize=None)
    '''
    point = seed
    while (True):
        neighbors = networkx.all_neighbors(graph, point)
        bestNeighbor = point
        bestValue = objective(point)
        print('point:\t\t',_str(graph,point), '\tobjective=',bestValue)
        for neighbor in neighbors:
            value = objective(neighbor)
            print('neighbor:\t',_str(graph,neighbor), '\tobjective=',value)
            if value < bestValue:
                bestValue = value
                bestNeighbor = neighbor
        if bestNeighbor == point:
            return point
        point = bestNeighbor  # Descend!


def greedy_neighbor_descent(graph, objective, seed):
    '''
    Starting from a seed node, move to the first neighbor found that has a lower objective until a local minimum (or plateau) is reached. This is the special case of a beam search of width 1.

    For better performance, it is reccommended that you memoize your objective
    function, i.e. with @functools.lru_cache(maxsize=None)
    '''
    point = seed
    stillDescending = True
    while (True):
        neighbors = networkx.all_neighbors(graph, point)
        currentValue = objective(point)
        print('point:\t\t',_str(graph,point), '\tobjective=',currentValue)
        for neighbor in neighbors:
            value = objective(neighbor)
            print('neighbor:\t',_str(graph,neighbor), '\tobjective=',value)
            if value < currentValue:
                point = neighbor  # Descend!
                stillDescending=True
                break
            else:
                stillDescending=False
        if not stillDescending:
            return point


def exhaustive_search(graph, objective):
    ''' Try every node in your graph, brute force.
        You don't really need a graph for this; this is just for convenience. '''
    globalMinimum = None
    globalMinimumObjective = float('Inf')
    for point in graph.nodes():
        value = objective(point)
        if value < globalMinimumObjective:
            globalMinimumObjective = value
            globalMinimum = point
            print('new minimum:\t\t',_str(graph,point), '\tobjective=',globalMinimumObjective)
        else:
            print('visited point:\t\t',_str(graph,point), '\tobjective=',value)
    assert globalMinimum is not None, 'Global minimum not found. Did you pass an empty graph?'
    print('A global minimum is:\t',_str(graph,globalMinimum), '\tobjective=',value)
    return globalMinimum
