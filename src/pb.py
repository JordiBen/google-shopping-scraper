"""Minimal protobuf wire-format decode/encode (enough for Google Shopping data blobs and filter tokens)."""
import base64
import struct
def b64d(s): return base64.urlsafe_b64decode(s+'='*(-len(s)%4))
def varint(b,i):
    r=s=0
    while True:
        x=b[i]; i+=1; r|=(x&0x7f)<<s; s+=7
        if x<0x80: return r,i
def dec(b,depth=0):
    i=0; out=[]
    while i<len(b):
        k,i=varint(b,i); f,t=k>>3,k&7
        if t==0: v,i=varint(b,i); out.append((f,v))
        elif t==2:
            l,i=varint(b,i); v=b[i:i+l]; i+=l
            try:
                sub=dec(v,depth+1) if v and depth<6 else None
            except Exception: sub=None
            if sub is not None and not all(32<=c<127 for c in v): out.append((f,sub))
            else:
                try: out.append((f,v.decode()))
                except: out.append((f,v))
        elif t==1: out.append((f,b[i:i+8])); i+=8
        elif t==5: out.append((f,b[i:i+4])); i+=4
        else: raise ValueError('wt%d'%t)
    return out

def _v(n):
    out=bytearray()
    while True:
        b=n&0x7f; n>>=7
        if n: out.append(b|0x80)
        else: out.append(b); return bytes(out)
def enc(fields):
    out=b''
    for f,v in fields:
        if isinstance(v,bool) or isinstance(v,int): out+=_v(f<<3)+_v(int(v))
        elif isinstance(v,float): out+=_v(f<<3|1)+struct.pack('<d',v)
        elif isinstance(v,str): b=v.encode(); out+=_v(f<<3|2)+_v(len(b))+b
        elif isinstance(v,bytes): out+=_v(f<<3|2)+_v(len(v))+v
        elif isinstance(v,list): b=enc(v); out+=_v(f<<3|2)+_v(len(b))+b
    return out
def b64e(b): return base64.urlsafe_b64encode(b).decode().rstrip('=')
