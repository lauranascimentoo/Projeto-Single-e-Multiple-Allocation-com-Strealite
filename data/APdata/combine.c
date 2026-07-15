/* File: combine.c
   Authors: Mohan and Andreas
   Purpose: Combine nodes at the same x & y position
   */

#include <stdio.h>
#include <stdlib.h>

#define N_ROWS	 5				/* number of y subdivisions */
#define INPUT_FILE "/home/andreas/p-hub/data/austpost/d212X8.full"
#define NEW_ARRAY(x,type,size) if((x=(type *)malloc((size)*sizeof(type)))==NULL){fprintf(stderr,"ERROR: Out of memory in %s line %d\n",__FILE__,__LINE__);exit(1);} 

typedef struct{
  int i;						/* index in original */
  int new_i;					/* new index */
  double x,y;
} coordinate;

int y_compare(const void *a, const void *b)
{ if(((coordinate *) a)->y < ((coordinate *) b)->y) return -1;
  if(((coordinate *) a)->y > ((coordinate *) b)->y) return 1;
  if(((coordinate *) a)->x < ((coordinate *) b)->x) return -1;
  if(((coordinate *) a)->x > ((coordinate *) b)->x) return 1;
/*   fprintf(stderr,"ERROR: Two nodes at same location\n"); */
/*   exit(1); */
}


int x_compare(const void *a, const void *b)
{ if(((coordinate *) a)->x < ((coordinate *) b)->x) return -1;
  if(((coordinate *) a)->x > ((coordinate *) b)->x) return 1;
  if(((coordinate *) a)->y < ((coordinate *) b)->y) return -1;
  if(((coordinate *) a)->y > ((coordinate *) b)->y) return 1;
/*   fprintf(stderr,"ERROR: Two nodes at same location\n"); */
/*   exit(1); */
}

void main(int argc,char **argv)
{ int nn,np,p,q,r,NN;
  FILE *in = stdin; /* fopen(INPUT_FILE,"r"); */
  coordinate *pts;
  double **w,collect,transfer,distribute; /* volumes, O+D, and costs */
  int step,row_end,row_start,row_step,row_remainder;
  int n_cols,col_step,col_remainder,col_start,col_end;
  double *new_x,*new_y,**new_w;
  
  /* read file */
  fscanf(in,"%d %d",&NN,&np);	/* read in number of nodes & skip hub number */
  NEW_ARRAY(pts,coordinate,NN);
  for(p=0;p<NN;p++){
	fscanf(in,"%lf %lf",&pts[p].x,&pts[p].y);
	pts[p].i = p;
  }
  NEW_ARRAY(w,double *,NN);
  for(p=0;p<NN;p++){
	NEW_ARRAY(w[p],double,NN);
	for(q=0;q<NN;q++){
	  fscanf(in,"%lf",&w[p][q]);
	  w[p][q]/= 100000;
	}
  }
  fscanf(in,"%lf %lf %lf",&collect,&transfer,&distribute);
  fclose(in);

  /* Sort */
  qsort(pts,NN,sizeof(coordinate),&y_compare);

  /* Combine (renumber) */
  NEW_ARRAY(new_x,double,NN);/* really need nn but don't only know nn <=NN */
  NEW_ARRAY(new_y,double,NN);
  NEW_ARRAY(new_w,double*,NN);
  for(p=0;p<NN;p++){
	new_x[p] = new_y[p] = 0;
	NEW_ARRAY(new_w[p],double,NN);
	for(q=0;q<NN;q++) new_w[p][q] = 0;
  }
  /* p = index of next combined node
	 q = index of next original node
	 */
  for(p=q=0;q<NN;p++){
	new_x[p] = pts[q].x;
	new_y[p] = pts[q].y;
	for(;q < NN && new_x[p] == pts[q].x && new_y[p] == pts[q].y;q++)
	  pts[q].new_i = p;
  }
  nn = p;						/* new number of nodes */
  /* calculate new w's */
  for(p=0;p<NN;p++){
	for(q=0;q<NN;q++)
	  new_w[pts[p].new_i][pts[q].new_i] += w[pts[p].i][pts[q].i];	
  }

  /* Write out new problem */
  printf("%d\n",nn);
  for(p=0;p<nn;p++){
	printf("%5.0f %5.0f\n",new_x[p],new_y[p]);
  }
  for(p=0;p<nn;p++)
	for(q=0;q<nn;q++)
	  printf("%5.5f%c",new_w[p][q],((q==nn-1) ? '\n' : ' '));
  printf("%d\n%f\n%f\n%f\n",np,collect,transfer,distribute);  
}
	
