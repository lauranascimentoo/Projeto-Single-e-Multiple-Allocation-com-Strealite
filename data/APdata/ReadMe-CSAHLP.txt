This directory contains the AP data set for Capacitated Single Allocation
Hub Location Problems (CSAHLP). The files contain the following:

  APdata200  - Data file for a full 200 node problem with 8 hubs
  generate.c - C program for generating smaller data sets
               USAGE: generate n p < APdata200 > newdata
               This creates a new problem with n nodes and p hubs
	       [p is irrelevant for these types of problems]
  20         - A sample data set with 20 nodes produced by
               generate 20 3 < APdata200 > 20  
  FcostX.NN  - Fixed cost file for NN nodes where X = 'T' or 'L'
	       (the T problems tend to be more difficult) 
  CapY.NN    - Node capacity file for NN nodes where Y = 'T' or 'L'
	       (the T problems are more tightly constraint) 
  solutions  - Optimal solutions for all combinations of n with
               n in {10,20,25,40,50} and all combinations of 
	       tight (T) and lose (L) costs and capacities.
	       In the result files we use the nomenclature "NNXY"
	       to refer to the problem generatedfrom data files 
	       NN, FcostX.NN and CapY.NN 
               The objective is given as well as the allocation
               of hubs. Eg an allocation vector 2,2,4,4,4 means
               that nodes 2 & 4 are hubs, node 1 is allocated to
               hub node 2 and nodes 3 & 5 to hub node 4.


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

The costs and and capacity files contain one number for each node (in the
same order as in the nodes file). For FcostX.NN this represents the cost
of making the node a hub. For CapY.NN the numbers are the capacity on 
incoming commodities (including from the node itself) if that node is made 
a hub.

For further information on this problem see the article "Solution Algorithms
for the Capacitated Single Allocation Hub Location Problem" by AT Ernst &
M Krishnamoorthy in Annals of OR, Vol 85, pp. 141-159 (1999)
