#!/usr/bin/python3
# Recursively download chunked JS files

import argparse, sys, re, time, signal, requests, urllib3, hashlib, random, string
import os.path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
urllib3.disable_warnings()

class Resource:
  url = None
  content = None
  proxies = None
  contenttype = None
  paths = []
  
  def __init__( self, url, proxy=None ):
    self.url = url
    if proxy:
      self.proxies = {
        'http': proxy,
        'https': proxy
      }
  
  def fetch( self ):
    response = requests.get( 
      self.url, 
      proxies=self.proxies, 
      verify=False, 
      allow_redirects=True,
      headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
      }
    )
    if not response or not response.content: raise Exception("No file content found")
    if not str( response.status_code ).startswith('2'): raise Exception(str(response.status_code) + ' returned')
    self.content = response.content.decode()
    self.contenttype = response.headers.get('content-type')

    # Hash the content
    hash_object = hashlib.sha256(response.content)
    self.hash = hash_object.hexdigest()
    
    if 'javascript' in self.contenttype:
      self.__class__ = JsFile
    else:
      self.__class__ = HtmlFile
    return response

class HtmlFile( Resource ):
  jsfiles = []
  inlinejs = []
  js = None

  def parse( self ):
    
    # Fetch all references to JS files
    if not self.content:
      self.fetch()

    soup = BeautifulSoup( self.content, 'html.parser' )
    for script in soup.find_all('script'):
      src = script.get('src')
      if src: self.jsfiles.append( src )
      else: 
        if not script.content: continue
        self.inlinejs.append( script.content )

    if len( ''.join( self.inlinejs ).strip() ) > 0:
      self.js = JsFile( self.url )
      self.js.content = ''.join( self.inlinejs ).strip()
      self.js.parse()

  def get_js_urls( self ):
    rtn = []
    url = urlparse( self.url )

    # Directly referenced files
    for f in self.jsfiles:

      # Full URL
      if f.startswith('http://') or f.startswith('https://'):
        jsurl = f
      
      # Same protocol
      elif f.startswith('//'):
        jsurl = url.scheme + ':' + f

      # Same host
      elif f.startswith('/'):
        jsurl = url.scheme + '://' + url.netloc + f

      # Relative to current URL
      else:
        jsurl = url.scheme + '://' + url.netloc + os.path.join( os.path.dirname( url.path ), f )

      rtn.append( jsurl )

    # URLs guessed from inline JS
    if self.js:
      rtn = rtn + js.get_js_urls()

    rtn = list( set( rtn ) )
    return sorted( rtn )

class JsFile( Resource ):
  chunks = []
  paths = []

  def parse( self ):
    if not self.content:
      self.fetch()
    
    # Look for chunk dicts e.g. 
    # {9:"26454eb9ee6ea13543d9",93:"45fc526fb568708f9e75",143:"2db0078a50b60395832c",147:"639b3f4b2cece83f1dc6",196:"1935d7ca83c8c9f78d35",357:"c1aa5f68360b6152eee8",388:"2adc4ed40e19b760d6be",524:"ca3102c97c465e7d5bb9",538:"4f19f7c83859794eec0b",559:"754996081bd3dfb26c53",657:"e4e1530c94a831b372f6",708:"e48e8422b639e111336a",841:"ab409098350a39745824",872:"03afec38607d98403ddf",895:"aa50b9bbf6c2234a2257",964:"55b95372a229e9114c93"}
    chunkpattern = r'((\d+) *: *"([a-f0-9]{20}|[a-z][a-zA-Z0-9]+)")+,?'
    self.chunks = [(x[1],x[2]) for x in re.findall(chunkpattern, self.content)]
    
    # Looks for something which could be a path
    pathpattern = r'"(/[:_/a-zA-Z0-9.?=&-]+)"'
    self.paths = re.findall(pathpattern, self.content)
  
  def get_js_urls( self ):
    rtn = []
    url = urlparse( self.url )
    dirname = os.path.dirname( url.path )
    lookup = {}

    # Create lookup table of chunk names and hashes
    for chunk in self.chunks:
      if re.search(r'[a-f0-9]{20}',chunk[1]):
        lookup[chunk[0]] = chunk[1]

    # Resolve chunk names to hashes
    for chunk in self.chunks:
      if not re.search(r'[a-f0-9]{20}',chunk[1]) and chunk[0] in lookup:
        self.chunks.append((chunk[1],lookup[chunk[0]]))
   
    # Compile potentially correct paths to chunk files
    for chunk in self.chunks:
      dirname = url.scheme + '://' + url.netloc + os.path.dirname( url.path )
      rtn.append( dirname + chunk[0] + '.' + chunk[1] + '.js' )
    
    rtn = list( set( rtn ) )
    return sorted( rtn )

class ChunkSpider:
  
  foundfiles = []
  foundpaths = []
  hashes = []
  proxy = None
  originhost = None

  def __init__( self, proxy=None ):
    self.proxy = proxy

  def spider_url( self, url, savejs=None, samehost=None ):
   
    if not self.originhost:
      self.originhost = urlparse( url ).hostname

    # Fetch the URL
    res = Resource( url, proxy=self.proxy )
    try:
      res.fetch()
    except Exception as e:
      print( e )
      if url in self.foundfiles: self.foundfiles.remove( url )
      return
    
    # Skip identical content
    if res.hash in self.hashes: return
    self.hashes.append( res.hash )

    # Save the file
    if savejs:
      if not os.path.isdir( savejs ):
        os.makedirs( savejs )
        path = os.path.join( savejs, os.path.basename( re.url ) )
        with open( path, 'w' ) as f:
          f.write(res.content)
          print('Wrote to', path)

    # Parse out content
    res.parse()
    self.foundpaths = list(set( self.foundpaths + res.paths))
    for jsurl in res.get_js_urls():
      if samehost and self.originhost != urlparse( jsurl ).hostname: continue
      if jsurl in self.foundfiles: 
        continue
      print( 'Testing new JS URL:', jsurl )
      self.foundfiles.append( jsurl )
      self.spider_url( jsurl, savejs=savejs, samehost=samehost )
    self.foundfiles = sorted( list( set( self.foundfiles ) ) )
    self.foundpaths = sorted( list( set( self.foundpaths ) ) )

  def get_404_response( self, baseurl ):

    lengths = []
    codes = []

    # Try 10 random paths, see if code and length are the same
    for path in [ '/' + ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(20)) for x in range( 10 ) ]:
      response = requests.get( 
        baseurl + path, 
        proxies={'http':self.proxy,'https':self.proxy}, 
        verify=False, 
        allow_redirects=True,
        headers={
          'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
        }
      )
      codes.append( response.status_code )
      lengths.append( len( response.content ) )
      print( path, response.status_code, len(response.content) )

    return { 
      'code': max(set(codes), key=codes.count),
      'length': max(set(lengths), key=lengths.count)
    }

def main():
  
  parser = argparse.ArgumentParser(description="Recursively download chunked JS files")
  parser.add_argument("--proxy", help="URL of HTTP proxy to send requests through, e.g. http://localhost:8080")
  parser.add_argument("-P","--test-paths", action='store_true', help="Test observed path strings against the host from the first request")
  parser.add_argument("-p","--save-paths", help="Write found path strings to this file")
  parser.add_argument("-u","--save-urls", help="Write found URLs to this file")
  parser.add_argument("-j","--save-javascript", help="Write found JavaScript to this directory")
  parser.add_argument("-H","--same-host", action='store_true', help="Only spider JavaScript on the same host as the initial URL")
  parser.add_argument("url", help="URL or file containing list of URLs protected by basic auth")

  # Only fetch for these hosts
  args = parser.parse_args()

  spider = ChunkSpider( args.proxy )
  spider.spider_url( args.url, savejs=args.save_javascript, samehost=args.same_host )
  print('\nFound these URLs:\n')
  print('\n'.join(spider.foundfiles))
  print('\nThe following look like paths:\n')
  print('\n'.join(spider.foundpaths))

  if args.save_urls and len( spider.foundfiles ) > 0:
    with open( args.save_urls, 'w' ) as f:
      f.write('\n'.join(spider.foundfiles))
    print( 'URLs written to', args.save_urls )

  if args.save_paths and len( spider.foundpaths ) > 0:
    with open( args.save_paths, 'w' ) as f:
      f.write('\n'.join(spider.foundpaths))
    print( 'Path strings written to', args.save_paths )

  if args.test_paths:
    url = urlparse( args.url )
    baseurl = url.scheme + '://' + url.netloc
    if len(  spider.foundpaths ) > 0:
      print('\nTesting for typical 404 response...')
      fourohfour = spider.get_404_response( baseurl )
      print('\nTesting observed paths:\n')
      for path in spider.foundpaths:
        response = requests.get( 
          baseurl + path, 
          proxies={'http':args.proxy,'https':args.proxy}, 
          verify=False, 
          allow_redirects=True,
          headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
          }
        )
        reset = '\033[0m'
        match int(str(response.status_code)[0]):
          case 2:
            colour = '\033[32m'
            icon = '✅'
          case 3:
            colour = '\033[34m'
            icon = '➡️'
          case 4:
            colour = '\033[31m'
            icon = '❌'
            if response.status_code == 405:
              colour = '\033[33m'
              icon = '🚫'
          case 5:
            colour = '\033[33m'
            icon = '⚠️'
          case _:
            colour = ''

        if response.status_code == fourohfour['code'] and len( response.content ) == fourohfour['length']:
          colour = '\033[31m'
          icon = '❌'

        print( icon, colour + baseurl + path, response.status_code, len( response.content ), reset )
      

if __name__ == '__main__':
  main()
