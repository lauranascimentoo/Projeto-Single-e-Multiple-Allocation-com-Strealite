
#include <string>
#include<iomanip>
#include<iostream>
#include<fstream>
#include<cmath>
#include <stdio.h>


long int acs4d(int i,int j,int k,int l, int NodesNo) {
    return  (i*NodesNo*NodesNo*NodesNo + j*NodesNo*NodesNo + k*NodesNo + l);
}
long int acs2d(int i, int j, int NodesNo) {
    return (i*NodesNo+j);
}

using namespace std;

int main(int argc, char **argv) {


    int i,j,p,n;

   if(argc == 2){


        string datanp ;
        ifstream datafile;
    datanp =  argv[1];


    datafile.open(datanp.c_str());
    if(!datafile) {
        std::cerr << "No such file ***: " << datanp << std::endl;
        throw(-2);
        return 0;
    }
    datafile >> n;
    double *Cost,*FixedCost,*Qury;

    Cost= new double[n*n*n*n];
    FixedCost = new double[n];
    Qury = new double[n*n];
    double pos_xy[n][2],collCost, trnsCost, distCost;

    /* reading coordinates of nodes; to obtain the distances between nodes. */
    for (i = 0; i  < n; i++)
        for(j=0 ; j< 2; j++ )
            datafile >> pos_xy[i][j] ;


    /* Stores the query amount q_{ij}  */
    for (i = 0; i  < n; i++) {
        for(j=0 ; j< n; j++ )
            datafile >> Qury[acs2d(i,j,n)] ;
    }

    /* reading p: number of hubs, and discount factors of costs: alpha,beta,chi */
    datafile >> p;
    datafile >> collCost >> trnsCost >> distCost;


    datafile.close();
    //cout << collCost<<","<<trnsCost<<","<<distCost<<endl;



    /* Calculates the cost c_{ijkl}  */
    for (i = 0; i  < n; i++)
        for(j=0 ; j< n; j++ )
            for (int k=0; k < n; k++)
                for (int l=0; l< n ; l++) {
                    Cost[acs4d(i,j,k,l,n)] =  (collCost * sqrt( pow(pos_xy[i][0]-pos_xy[k][0],2) + pow(pos_xy[i][1]-pos_xy[k][1],2) ) +
                                                      trnsCost * sqrt( pow(pos_xy[k][0]-pos_xy[l][0],2) + pow(pos_xy[k][1]-pos_xy[l][1],2) ) +
                                                      distCost * sqrt( pow(pos_xy[l][0]-pos_xy[j][0],2) + pow(pos_xy[l][1]-pos_xy[j][1],2) ));
                }


    //center of mass
    double xc=0,yc=0;
    for (i = 0; i  < n; i++) {
            xc+= pos_xy[i][0];
            yc+= pos_xy[i][1];
        }
    xc = (double) xc /n;
    yc = (double) yc /n;

    //closest node to cener of mass:
    int h=0;
    for (i = 1; i  < n; i++) {
        double newntoC = pow(pos_xy[i][0]-xc,2) + pow(pos_xy[i][1]-yc,2);
        double htoC = pow(pos_xy[h][0]-xc,2) + pow(pos_xy[h][1]-yc,2);
        if(newntoC< htoC)
            h=i;
    }


    double fo=0;
    for (i = 0; i  < n; i++)
        for(j=0 ; j< n; j++ ){
            fo += Cost[acs4d(i,j,h,h,n)]  * Qury[acs2d(i,j,n)];
        }

    for (i = 0; i  < n; i++)
        for(j=0 ; j< n; j++ ){
             fo -= Cost[acs4d(i,j,i,j,n)] * Qury[acs2d(i,j,n)];
        }
    fo = (double)fo/n;


    double *di = new double[n];
    double dm=0;

    for(i=0;i<n;i++){
        di[i] = sqrt(pow(pos_xy[i][0]-xc,2) + pow(pos_xy[i][1]-yc,2));
        if (dm<di[i]) dm = di[i];
    }

    for(i=0;i<n;i++){
        FixedCost[i] = (double) fo * (1 -  (double)(0.6 * di[i]/ dm) ) ;
        cout<< std::setprecision(10) <<FixedCost[i]<<"\t";
    }
cout<< "\n";
 delete[] Cost,FixedCost,di,Qury;

     }
else
 cout << "input FileNP; output: Fcost.n\n";


return 0;
}
