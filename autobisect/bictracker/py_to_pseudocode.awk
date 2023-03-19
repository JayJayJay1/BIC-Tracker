match($0, "^def (.*)$", ary) { 
    print "\begin{algorithm}
\caption{" ary[1] "}\label{alg:cap}
\begin{algorithmic}[1]"
}
{print "ERROR:" $0}