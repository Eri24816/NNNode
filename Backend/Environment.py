from __future__ import annotations
from typing import Dict
from history import *
import edge
import node
import queue
import inspect


class num_iter:
    def __init__(self,start=-1):
        self.i=start
    def next(self):
        self.i+=1
        return self.i



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
        self.first_history=self.latest_history=History_item("stt") # first history item
        self.lock_history=False # when undoing or redoing, lock_history will be set to True to avoid unwanted history change
        
        self.current_history_sequence_id = -1

        # unlike history, some types of changes aren't necessary needed to be updated sequentially on client, like code in a node or whether the node is running.
        # one buffer per client
        # format:[ { "<command>/<node id>": <value> } ]
        # it's a dictionary so replicated updates will overwrite
        self.update_message_buffers = []

        # for run() thread
        self.nodes_to_run = queue.Queue()
        self.running_node : node.Node = None
        
    class History_sequence():
        next_history_sequence_id = 0
        def __init__(self,env):
            self.env=env
        def __enter__(self):
            self.env.current_history_sequence_id = self.next_history_sequence_id
            self.next_history_sequence_id += 1
        def __exit__(self, type, value, traceback):
            self.env.current_history_sequence_id = -1   
    
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
            with self.History_sequence(self): # removing a node may cause some edges also being removed. When undoing and redoing, these multiple actions should be done in a sequence.
                self.nodes[info['id']].remove()

    
    def Update_history(self,type,content):
        '''
        type, content:
            stt, None - start the environment
            new, info - new node or edge
            rmv, info - remove node or edge
            atr, name, old, new
        '''
        if self.lock_history:
            return
        # don't repeat mov history
        if type=="mov" and self.latest_history.type=="mov" and content['id'] == self.latest_history.content['id']:
            if (datetime.datetime.now() - self.latest_history.time).seconds<3:
                self.latest_history.content['new']=content['new']
                self.latest_history.version+=1
                return

        # add an item to the linked list
        self.latest_history=History_item(type,content,self.latest_history,self.current_history_sequence_id)

    
    def Write_update_message(self, id, command, v = ''):
        '''
        out - output
        cod - code
        clr - clear_output
        new - create a demo node
        '''
        priority = 5 # the larger the higher
        if command == 'new':
            priority = 8
        
        k=str(9-priority)+command+"/"+str(id)
        if command == 'new':
            k+='/'+v['type']
        if command == 'atr':
            k+='/'+v
        for buffer in self.update_message_buffers:
            if command == 'out':
                if k not in buffer:
                    buffer[k] = ''
                buffer[k]+=v
            elif command == 'clr':
                buffer[str(9-priority)+"out/"+id] = ''
                buffer[k]=v
            else:
                buffer[k]=v

    def Undo(self):
        if self.latest_history.last==None:
            return 0 # noting to undo
        # undo
        with History_lock(self):
            type=self.latest_history.type
            content=self.latest_history.content

            if type == "new":
                if content['id'] in self.nodes:
                    self.latest_history.content=self.nodes[content['id']].get_info()
                self.Remove(content)
                
            elif type=="rmv":
                self.Create(content)
            elif type=="mov":
                self.Move(content['id'],content['old'])

        self.latest_history.head_direction = -1

        seq_id_a = self.latest_history.sequence_id
        
        self.latest_history=self.latest_history.last
        self.latest_history.head_direction = 0

        seq_id_b = self.latest_history.sequence_id
        
        if seq_id_a !=-1 and seq_id_a == seq_id_b:
            self.Undo()

        return 1

    def Redo(self):
        if self.latest_history.next==None:
            return 0 # noting to redo
        self.latest_history.head_direction=1
        self.latest_history=self.latest_history.next
        self.latest_history.head_direction=0

        with History_lock(self):
            type=self.latest_history.type
            content=self.latest_history.content
            
            if type=="new":
                self.Create(content)
            elif type=="rmv":
                self.Remove(content)
            elif type=="mov":
                self.Move(content['id'],content['new'])

        seq_id_a = self.latest_history.sequence_id

        seq_id_b =  self.latest_history.next.sequence_id if self.latest_history.next!=None else -1

        if seq_id_a !=-1 and seq_id_a == seq_id_b:
            self.Redo()

        return 1

    def update_demo_nodes(self):
        # In a regular create node process, we call self.Create() to generate a history item (command = "new"), 
        # which will later be sent to client.
        # However, demo nodes creation should not be undone, so here we put the message "new" in update_message buffer.
        for node_class in self.node_classes.values():
            self.Write_update_message(-1,'new',node_class.get_class_info())

    # run in another thread from the main thread (server.py)
    def run(self):
        self.flag_exit = 0
        while not self.flag_exit:
            self.running_node = self.nodes_to_run.get()
            if self.running_node == 'EXIT_SIGNAL':
                return
            self.running_node.run()
            