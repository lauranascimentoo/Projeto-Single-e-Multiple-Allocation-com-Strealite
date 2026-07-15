This directory contains the AP data set for Capacitated Single Allocation
Hub Location Problems (CSAHLP). The files contain the following:

  APdata200  - Data file for a full 200 node problem with 8 hubs
  generate.c - C program for generating smaller data sets
               USAGE: generate n p < APdata200 > newdata
               This creates a new problem with n nodes and p hubs
  genfcost.cpp - C++ program for generating fixed costs
  40.4       - A sample data set with 40 nodes & 4 hubs produced by
               generate 50 5 APdata200 > 40.4  
  Fcost.NN   - Fixed cost file for NN nodes 


Data file format for nodes file: 
<n>                                     Number of nodes
<x[1]> <y[1]>                           x & y coordinates of node 1
  :
  :
<x[n]> <y[n]>                           x & y coordinates of node n
<w[1][1]> <w[1][2]> ... <w[1][n]>       flow from node 1 to all others
  :         :             :
  :         :             :
<w[n][1]> <w[n][2]> ... <w[n][n]>       flow from node n to all others
<p>                                     Number of hubs [IGNORE !]
<c>                                     Collection cost
<t>                                     Transfer cost
<d>                                     Distribution cost

All of the costs are per unit (euclidean) distance, per unit flow volume.

The costs files contain one number for each node (in the same order as
in the nodes file). For Fcost.NN this represents the cost of making
the node a hub. 

For further information on this problem see the article "The
2-allocation p-hub median problem and a modified Benders decomposition
method for solving hub location problems" by H Mokhtar, M
Krishnamoorthy, AT Ernst - Computers & Operations Research, vol.104,
pp. 375-393, 2019.
