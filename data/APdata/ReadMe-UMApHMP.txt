This directory contains the AP data set for Uncapacitated Multiple Allocation
p-Hub Median Problems (UMApHMP). The files contain the following:

  APdata200  - Data file for a full 200 node problem with 8 hubs
  generate.c - C program for generating smaller data sets
               USAGE: generate n p < APdata200 > newdata
               This creates a new problem with n nodes and p hubs
  20.3       - A sample data set with 20 nodes and 3 hubs produced by
               generate 20 3 < APdata200 > 20.3
  solutions  - Optimal solutions for all combinations of n,p with 
	       n in {10,20,25,40,50} and p in {2,3,4,5}
               Gives objective values and hubs
  flows      - As `solutions' but also gives a flow matrix. This matrix
               contains entries F[i][j] representing the total flow from 
	       node i to node j. If both i and j are hubs these are 
	       transfers, else they are collection or distribution flows.


Data file format:
<n>                                     Number of nodes
<x[1]> <y[1]>                           x & y coordinates of node 1
  :
  :
<x[n]> <y[n]>                           x & y coordinates of node n
<w[1][1]> <w[1][2]> ... <w[1][n]>       flow from node 1 to all others
  :         :             :
  :         :             :
<w[n][1]> <w[n][2]> ... <w[n][n]>       flow from node n to all others
<p>                                     Number of hubs
<c>                                     Collection cost
<t>                                     Transfer cost
<d>                                     Distribution cost

All of the costs are per unit (euclidean) distance, per unit flow volume.

For further information on this problem see the articles "Efficient algorithms
for the uncapacitated multiple allocation p-hub Median problem" by AT Ernst &
M Krishnamoorthy in EJOR, Vol 104, pp 100-112 (1998). 

