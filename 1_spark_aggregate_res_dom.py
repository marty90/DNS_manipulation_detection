#!/usr/bin/python

import json
import sys
import pyasn
from collections import Counter
from pyspark import SparkConf, SparkContext

# INPUT
in_log=sys.argv[1]
out_aggregated=sys.argv[2]


def main():
 
    conf = (SparkConf()
             .setAppName("Rogue DNS Resolvers Discovery - Aggregation (Resolver, Domain)")
             .set("spark.dynamicAllocation.enabled", "false")
             .set("spark.task.maxFailures", 128)
             .set("spark.yarn.max.executor.failures", 128)
             .set("spark.executor.cores", "8")
             .set("spark.executor.memory", "7G")
             .set("spark.executor.instances", "500")
             .set("spark.network.timeout", "300")
    )
    
    sc = SparkContext(conf = conf)
    log=sc.textFile(in_log)

    # Parse each line of the ATA DNS log file
    log_mapped=log.mapPartitions(emit_tuples)

    # Reduce tuples, aggregate by (resolver, domain)
    log_reduced=log_mapped.reduceByKey(reduce_tuples)

    # Put in final format
    log_final=log_reduced.map(final_map)

    # Save on file
    log_final.saveAsTextFile(out_aggregated)



def emit_tuples(lines):

    # Create a pyasn to get ASNs
    asndb = pyasn.pyasn('ASN_VIEW_2017')
    
    # Iterate over the lines
    for line in lines:
        try:
        
            # Parse the lines
            fields=parse_line(line)
            # Handle the two log formats (short and long)
            if len(fields) == 45:
                NB,FT,SMAC,DMAC,DST,SRC,PROTO,BYTES,SPT,DPT,SID,DQ,DQNL,\
                DQC,DQT,DRES,DFAA,DFTC,\
                DFRD,DFRA,DFZ0,DFAD,DFCD,DANCOUNT,DANS,DANTTLS,\
                _IPV,_IPTTL,_DOPCODE,_DQDCOUNT,_DNSCOUNT,_DARCOUNT,_DANTYPES,_DANLENS,_DANLEN,\
                _DAUTHDATA,_DAUTHTYPES,_DAUTHTTLS,_DAUTHLENS,_DAUTHLEN,_DADDDATA,\
                _DADDTYPES,_DADDTTLS,_DADDLENS,_DADDLEN \
                =fields
            else:
                FT,TT,DUR,SMAC,DMAC,SRC,DST,OUT,IN,BYTES,PROTO,SPT,DPT,SID,DQ,DQNL,\
                DQC,DQT,DRES,DFAA,DFTC,\
                DFRD,DFRA,DFZ0,DFAD,DFCD,DANCOUNT,DANS,DANTTLS,\
                _IPV,_IPTTL_q,_IPTTL_r,_DOPCODE,_DQDCOUNT,_DNSCOUNT,_DARCOUNT,_DANTYPES,_DANLENS,_DANLEN,\
                _DAUTHDATA,_DAUTHTYPES,_DAUTHTTLS,_DAUTHLENS,_DAUTHLEN,_DADDDATA,\
                _DADDTYPES,_DADDTTLS,_DADDLENS,_DADDLEN \
                =fields
            
            # Keep only NOERROR responses and recursive queries
            if DRES == "NOERROR" and DFRD == "1" and DFRA == "1":
            
                # Get Number of CNAMEs and Server IP addresses
                records=str(DANS).split('|-><-|')
                sip=set()
                clen=0
                nip=0
                for record in records:
                    if is_valid_ipv4(record):
                        sip.add(record)
                        nip+=1
                    else:
                        clen+=1
                
                # Continue only if at least one IP address has been returned
                if nip > 0:      
                    # Get the list of ASNs from he server IPs
                    asn=[]
                    for ip in sip:
                        try:
                            this_asn = str(asndb.lookup(ip)[0])
                            if this_asn == "None":
                                this_asn = ".".join(ip.split(".")[0:2]  ) + ".0.0"
                            if ip.startswith("127.0."):
                                this_asn=ip
                        except Exception as e:
                            this_asn=ip
                        asn.append(this_asn)

                    # Get last TTL. In case multiple are present, the last refers to A records  
                    ttl=int(str(DANTTLS).split(",")[-1] )  
                      
        
                    # Create the aggregation key
                    key=(str(DST),str(DQ).lower())
                    
                    # Create the value
                    value=(1, Counter((clen,)), Counter((nip,)), Counter(asn),Counter((ttl,)), Counter(sip) )
            
                    # Emit a tuple
                    tup=(key,value)
                    yield tup

        except:
            pass

# Reduce is just merging the two sets
def reduce_tuples(tup1,tup2):
    n1, clen1,nip1,asn1,ttl1,sip1=tup1
    n2, clen2,nip2,asn2,ttl2,sip2=tup2

    return (n1+n2, clen1+clen2, \
                   nip1+nip2,   \
                   asn1+asn2,   \
                   ttl1+ttl2,   \
                   sip1+sip2  )
                   
# In the end, just print the Counter in a Pandas friendly format
def final_map(tup):
    (res,fqdn), (n, clen,nip,asn,ttl,sip) = tup

    n_str=str(n)
    clen_str='"' + json.dumps(clen).replace('"','""').replace(",",";")+ '"'
    nip_str= '"' + json.dumps(nip).replace('"','""').replace(",",";")+ '"'
    asn_str= '"' + json.dumps(asn).replace('"','""').replace(",",";")+ '"'
    ttl_str= '"' + json.dumps(ttl).replace('"','""').replace(",",";")+ '"'
    sip_str= '"' + json.dumps(sip).replace('"','""').replace(",",";")+ '"'

    return ",".join([fqdn,res,n_str,clen_str,nip_str,asn_str,ttl_str,sip_str])

# Check if an IPv4 is valid
def is_valid_ipv4(s):
    a = s.split('.')
    if len(a) != 4:
        return False
    for x in a:
        if not x.isdigit():
            return False
        i = int(x)
        if i < 0 or i > 255:
            return False
    return True
 

def parse_line(line):
    fields = []
    current_field=""
    in_quote=False
    for c in line:
        if not in_quote and c == ",":
            fields.append(current_field)
            current_field=""
        elif in_quote and c == '"':
            in_quote=False
        elif not in_quote and c == '"':
            in_quote=True
        else:
            current_field+=c
    fields.append(current_field)
    return fields
       
main()



