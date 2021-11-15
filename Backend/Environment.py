from __future__ import annotations
import asyncio
from asyncio.queues import Queue
from typing import Dict
from history import *
import edge
import node
from collections import deque
from threading import Event
import inspect

# from server import Send_all
# Above line causes circular import error so just define Send_all() again here.
import json
def Send_all(ws_list,message):
    for ws in ws_list:
        ws.send(json.dumps(message))


class num_iter:
    def __init__(self,start=-1):
        self.i=start
    def next(self):
        self.i+=1
        return self.i

class MyDeque(deque):
    # https://stackoverflow.com/questions/56821682/having-the-deque-with-the-advantages-of-queue-in-a-thread
    def __init__(self):
        super().__init__()
        self.not_empty = Event()
        #self.not_empty.set()

    def append(self, elem):
        super().append(elem)
        self.not_empty.set()

    def appendleft(self, elem):
        super().appendleft(elem)
        self.not_empty.set()

    def pop(self):
        self.not_empty.wait()  # Wait until not empty, or next append call
        if not (len(self) - 1):
            self.not_empty.clear()
        return super().pop()

# the environment to run the code in
class Env():
    '''
    node_modules = [function]
    node_classes = \
    [
        node.CodeNode,
        node.EvalAssignNode
    ]
    module = ''
    for module in node_modules:
        for m in inspect.getmembers(module, inspect.isclass):
            if m[1].__module__ == module.__name__:
                node_classes.append(m[1])
   '''
    node_classes = {}
    for m in inspect.getmembers(node, inspect.isclass):
        node_classes.update({m[0]:m[1]})

    def __init__(self,name):
        self.name=name
        self.thread=None
        self.id_iter = num_iter(-1)
        self.nodes: Dict[str,node.Node] = {} # {id : Node}
        self.edges={} # {id : Edge}
        self.globals=globals()
        self.locals={}

        self.history = History()

        # unlike history, some types of changes aren't necessary needed to be updated sequentially on client, like code in a node or whether the node is running.
        # one buffer per client
        # format:[ { "<command>/<node id>": <value> } ]
        # it's a dictionary so replicated updates will overwrite
        self.message_buffer = {}
        self.ws_clients = []

        # for run() thread

        self.node_stack = MyDeque()
        self.running_node : node.Node = None
        

    
    def Create(self,info:node.Node.Info): 
        '''
        Create any type of node or edge in the environment
        '''
        # info: {id, type, ...}
        type = info['type']
        if type == 'ControlFlow':
            c = edge.ControlFlow
        elif type == 'DataFlow':
            c = edge.DataFlow
        else:
            c = self.node_classes[type]
        new_instance = c(info,self)

        id=info['id']
        if info['type']=="DataFlow" or info['type']=="ControlFlow":
            assert id not in self.edges
            self.edges.update({id:new_instance})
        else:
            assert id not in self.nodes
            self.nodes.update({id:new_instance})

    def Remove(self,info): # remove any type of node or edge
        if info['id'] in self.edges:
            self.edges[info['id']].remove()
            
        else:
            with self.history.sequence(): # removing a node may cause some edges also being removed. When undoing and redoing, these multiple actions should be done in a sequence.
                self.nodes[info['id']].remove()

    def Update_history(self,type,content):
        '''
        When an attribute changes or something is created or removed, this will be called.
        If such action is caused by undo/redo, history.lock() prevents history.Update() working.
        '''
        # don't repeat atr history within 2 seconds 
        if type=="atr" and self.history.current.type=="atr" and content['id'] == self.history.current.content['id']:
            if (time.time() - self.history.current.time)<2:
                self.history.current.content['new']=content['new']
                self.history.current.version+=1
                return

        self.history.Update(type,content)

    def Add_direct_message(_, message):
        '''
        This will be overwritten by server.py
        '''
        pass

    def Add_buffered_message(self,id,command,content = ''):
        '''
        new - create a demo node
        out - output
        clr - clear output
        atr - set attribute
        '''

        priority = 5 # the larger the higher, 0~9
        if command == 'new':
            priority = 8
        
        k=str(9-priority)+command+"/"+str(id)
        if command == 'new':
            k+='/'+content['type']
        if command == 'atr':
            k+='/'+content

        if command == 'out':
            if k not in self.message_buffer:
                self.message_buffer[k] = ''
            self.message_buffer[k]+=content
        elif command == 'clr':
            self.message_buffer[str(9-priority)+"out/"+id] = ''
            self.message_buffer[k]=content
        else:
            self.message_buffer[k]=content

    def Undo(self):
        if self.history.current.last==None:
            return 0 # noting to undo

        # undo
        self.history.current.direction = -1
        type=self.history.current.type
        content=self.history.current.content

        with self.history.lock():
            if type == "new":
                if content['id'] in self.nodes:
                    self.history.current.content=self.nodes[content['id']].get_info()
                self.Remove(content)
            elif type=="rmv":
                self.Create(content)
            elif type=="atr":
                self.nodes[content['id']].attributes[content['name']].set(content['old'])

        seq_id_a = self.history.current.sequence_id
        
        self.history.current=self.history.current.last

        seq_id_b = self.history.current.sequence_id
        
        if seq_id_a !=-1 and seq_id_a == seq_id_b:
            self.Undo() # Continue undo backward through the action sequence

        return 1

    def Redo(self):
        if self.history.current.next==None:
            return 0 # noting to redo

        self.history.current=self.history.current.next
        self.history.current.direction=1
        type=self.history.current.type
        content=self.history.current.content

        with self.history.lock():
            if type=="new":
                self.Create(content)
            elif type=="rmv":
                self.Remove(content)
            elif type=="atr":
                self.nodes[content['id']].attributes[content['name']].set(content['new'])

        seq_id_a = self.history.current.sequence_id

        seq_id_b =  self.history.current.next.sequence_id if self.history.current.next!=None else -1

        if seq_id_a !=-1 and seq_id_a == seq_id_b:
            self.Redo() # Continue redo forword through the action sequence

        return 1

    def update_demo_nodes(self):
        # In a regular create node process, we call self.Create() to generate a history item (command = "new"), 
        # which will later be sent to client.
        # However, demo nodes creation should not be undone, so here we put the message "new" in update_message buffer.
        for node_class in self.node_classes.values():
            self.Add_direct_message({'command':'new','info':node_class.get_class_info()})

    # run in another thread from the main thread (server.py)
    def run(self):
        self.flag_exit = 0
        while not self.flag_exit:
            self.running_node = self.node_stack.pop()
            if self.running_node == 'EXIT_SIGNAL':
                return

            self.running_node.run()
                