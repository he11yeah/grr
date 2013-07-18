#!/usr/bin/env python
# Copyright 2012 Google Inc. All Rights Reserved.

"""Tests for the standard hunts."""



import time


from grr.lib import aff4
from grr.lib import hunts
from grr.lib import rdfvalue
from grr.lib import test_lib


class SampleHuntMock(object):

  def __init__(self, failrate=2):
    self.responses = 0
    self.data = "Hello World!"
    self.failrate = failrate
    self.count = 0

  def StatFile(self, args):
    return self._StatFile(args)

  def _StatFile(self, args):
    req = rdfvalue.ListDirRequest(args)
    response = rdfvalue.StatEntry(
        pathspec=req.pathspec,
        st_mode=33184,
        st_ino=1063090,
        st_dev=64512L,
        st_nlink=1,
        st_uid=139592,
        st_gid=5000,
        st_size=len(self.data),
        st_atime=1336469177,
        st_mtime=1336129892,
        st_ctime=1336129892)

    self.responses += 1

    self.count += 1
    if self.count == self.failrate:
      self.count = 0
      raise IOError("File does not exist")

    return [response]

  def TransferBuffer(self, args):
    response = rdfvalue.BufferReference(args)

    response.data = self.data
    response.length = len(self.data)
    return [response]


class StandardHuntTest(test_lib.FlowTestsBaseclass):
  """Tests the Hunt."""

  def setUp(self):
    super(StandardHuntTest, self).setUp()
    # Set up 10 clients.
    self.client_ids = self.SetupClients(10)

  def tearDown(self):
    super(StandardHuntTest, self).tearDown()
    self.DeleteClients(10)

  def testGenericHuntWithSendRepliesSetToFalse(self):
    """This tests running the hunt on some clients."""
    hunt = hunts.GRRHunt.StartHunt(
        "GenericHunt",
        flow_name="GetFile",
        args=rdfvalue.Dict(
            pathspec=rdfvalue.PathSpec(
                path="/tmp/evil.txt",
                pathtype=rdfvalue.PathSpec.PathType.OS,
                )
            ),
        collect_replies=False,
        token=self.token)

    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    # Pretend to be the foreman now and dish out hunting jobs to all the
    # client..
    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in self.client_ids:
      foreman.AssignTasksToClient(client_id)

    # Run the hunt.
    client_mock = SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, self.client_ids,
                            check_flow_errors=False, token=self.token)

    # Stop the hunt now.
    hunt.Stop()
    hunt.Save()

    hunt_obj = aff4.FACTORY.Open(hunt.session_id, age=aff4.ALL_TIMES,
                                 token=self.token)

    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    finished = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.FINISHED)
    errors = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.ERRORS)

    self.assertEqual(len(set(started)), 10)
    self.assertEqual(len(set(finished)), 10)
    self.assertEqual(len(set(errors)), 5)

    # We shouldn't receive any entries as send_replies is set to False.
    self.assertRaises(IOError, aff4.FACTORY.Open, hunt.state.collection.urn,
                      "RDFValueCollection", "r", False, self.token)

  def testGenericHunt(self):
    """This tests running the hunt on some clients."""
    hunt = hunts.GRRHunt.StartHunt(
        "GenericHunt",
        flow_name="GetFile",
        args=rdfvalue.Dict(
            pathspec=rdfvalue.PathSpec(
                path="/tmp/evil.txt", pathtype=rdfvalue.PathSpec.PathType.OS)),
        collect_replies=True,
        token=self.token)

    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    # Pretend to be the foreman now and dish out hunting jobs to all the
    # client..
    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in self.client_ids:
      foreman.AssignTasksToClient(client_id)

    # Run the hunt.
    client_mock = SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, self.client_ids, False, self.token)

    # Stop the hunt now.
    hunt.Stop()
    hunt.Save()

    hunt_obj = aff4.FACTORY.Open(hunt.session_id, age=aff4.ALL_TIMES,
                                 token=self.token)

    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    finished = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.FINISHED)
    errors = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.ERRORS)

    self.assertEqual(len(set(started)), 10)
    self.assertEqual(len(set(finished)), 10)
    self.assertEqual(len(set(errors)), 5)

    collection = aff4.FACTORY.Open(hunt.state.collection.urn, mode="r",
                                   token=self.token)

    # We should receive stat entries.
    i = 0
    for i, x in enumerate(collection):
      self.assertEqual(x.payload.__class__, rdfvalue.StatEntry)
      self.assertEqual(x.payload.aff4path.Split(2)[-1], "fs/os/tmp/evil.txt")

    self.assertEqual(i, 4)

  def testVariableGenericHunt(self):
    """This tests running the hunt on some clients."""

    flows = {
        rdfvalue.ClientURN("C.1%015d" % 1): [
            ("GetFile", dict(
                pathspec=rdfvalue.PathSpec(
                    path="/tmp/evil1.txt",
                    pathtype=rdfvalue.PathSpec.PathType.OS),
                ))],
        rdfvalue.ClientURN("C.1%015d" % 2): [
            ("GetFile", dict(
                pathspec=rdfvalue.PathSpec(
                    path="/tmp/evil2.txt",
                    pathtype=rdfvalue.PathSpec.PathType.OS),
                )),
            ("GetFile", dict(
                pathspec=rdfvalue.PathSpec(
                    path="/tmp/evil3.txt",
                    pathtype=rdfvalue.PathSpec.PathType.OS),
                ))],
        }

    hunt = hunts.GRRHunt.StartHunt("VariableGenericHunt", flows=flows,
                                   collect_replies=True, token=self.token)
    hunt.Run()
    hunt.ManuallyScheduleClients()

    # Run the hunt.
    client_mock = SampleHuntMock(failrate=100)
    test_lib.TestHuntHelper(client_mock, self.client_ids, False, self.token)

    # Stop the hunt now.
    hunt.Stop()
    hunt.Save()

    hunt_obj = aff4.FACTORY.Open(hunt.session_id, age=aff4.ALL_TIMES,
                                 token=self.token)

    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    finished = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.FINISHED)
    errors = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.ERRORS)

    self.assertEqual(len(set(started)), 2)
    self.assertEqual(len(set(finished)), 2)
    self.assertEqual(len(set(errors)), 0)

    collection = aff4.FACTORY.Open(hunt.state.collection.urn, mode="r",
                                   token=self.token, age=aff4.ALL_TIMES)

    # We should receive stat entries.
    self.assertEqual(len(collection), 3)

    collection = sorted([x for x in collection],
                        key=lambda x: x.payload.aff4path)
    stats = [x.payload for x in collection]
    self.assertEqual(stats[0].__class__, rdfvalue.StatEntry)

    self.assertEqual(stats[0].aff4path.Split(2)[-1], "fs/os/tmp/evil1.txt")
    self.assertEqual(collection[0].source, "aff4:/C.1%015d" % 1)
    self.assertEqual(stats[1].__class__, rdfvalue.StatEntry)
    self.assertEqual(stats[1].aff4path.Split(2)[-1], "fs/os/tmp/evil2.txt")
    self.assertEqual(collection[1].source, "aff4:/C.1%015d" % 2)
    self.assertEqual(stats[2].__class__, rdfvalue.StatEntry)
    self.assertEqual(stats[2].aff4path.Split(2)[-1], "fs/os/tmp/evil3.txt")
    self.assertEqual(collection[2].source, "aff4:/C.1%015d" % 2)

  def testHuntTermination(self):
    """This tests that hunts with a client limit terminate correctly."""

    old_time = time.time
    try:
      time.time = lambda: 1000

      args = rdfvalue.Dict(
          pathspec=rdfvalue.PathSpec(
              path="/tmp/evil.txt",
              pathtype=rdfvalue.PathSpec.PathType.OS)
          )

      hunt = hunts.GRRHunt.StartHunt(
          "GenericHunt", flow_name="GetFile", args=args,
          collect_replies=False, client_limit=5,
          expiry_time=rdfvalue.Duration("1000s"),
          token=self.token)

      regex_rule = rdfvalue.ForemanAttributeRegex(
          attribute_name="GRR client",
          attribute_regex="GRR")
      hunt.AddRule([regex_rule])
      hunt.Run()

      # Pretend to be the foreman now and dish out hunting jobs to all the
      # client..
      foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
      for client_id in self.client_ids:
        foreman.AssignTasksToClient(client_id)

      # Run the hunt.
      client_mock = SampleHuntMock()
      test_lib.TestHuntHelper(client_mock, self.client_ids,
                              check_flow_errors=False, token=self.token)

      hunt_obj = aff4.FACTORY.Open(hunt.session_id, age=aff4.ALL_TIMES,
                                   token=self.token)

      started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
      finished = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.FINISHED)
      errors = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.ERRORS)

      self.assertEqual(len(set(started)), 5)
      self.assertEqual(len(set(finished)), 5)
      self.assertEqual(len(set(errors)), 2)

      # Now advance the time such that the hunt expires.
      time.time = lambda: 5000

      # Erase the last foreman check time for one client.
      client = aff4.FACTORY.Open(self.client_ids[0], mode="rw",
                                 token=self.token)
      client.Set(client.Schema.LAST_FOREMAN_TIME(0))
      client.Close()

      # Let one client check in, this expires the rules and terminates the hunt.
      foreman.AssignTasksToClient(self.client_ids[0])

      # Now emulate a worker.
      worker = test_lib.MockWorker(queue_name="W", token=self.token)
      while worker.Next():
        pass
      worker.pool.Join()

      hunt_obj = aff4.FACTORY.Open(hunt.session_id, age=aff4.ALL_TIMES,
                                   token=self.token)
      self.assertEqual(hunt_obj.state.context.state,
                       rdfvalue.Flow.State.TERMINATED)

    finally:
      time.time = old_time

  def testHuntModificationWorksCorrectly(self):
    """This tests running the hunt on some clients."""
    hunt = hunts.GRRHunt.StartHunt(
        "GenericHunt", flow_name="GetFile",
        args=rdfvalue.Dict(
            pathspec=rdfvalue.PathSpec(
                path="/tmp/evil.txt",
                pathtype=rdfvalue.PathSpec.PathType.OS),
            ),
        collect_replies=True,
        client_limit=1,
        token=self.token)

    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    # Forget about hunt object, we'll use AFF4 for everything.
    hunt_session_id = hunt.session_id
    hunt = None

    # Pretend to be the foreman now and dish out hunting jobs to all the
    # client..
    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in self.client_ids:
      foreman.AssignTasksToClient(client_id)

    # Run the hunt.
    client_mock = SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, self.client_ids, False, self.token)

    hunt_obj = aff4.FACTORY.Open(hunt_session_id, age=aff4.ALL_TIMES,
                                 token=self.token)

    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    # There should be only one client, due to the limit
    self.assertEqual(len(set(started)), 1)

    hunt_obj = aff4.FACTORY.Open(hunt_session_id, mode="rw", token=self.token)
    hunt_obj.state.context.client_limit = 10
    hunt_obj.Close()

    # Read the hunt we've just written.
    hunt = aff4.FACTORY.Open(hunt_session_id, mode="rw", token=self.token)
    hunt.Pause()
    hunt.Run()

    # Pretend to be the foreman now and dish out hunting jobs to all the
    # client..
    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in self.client_ids:
      foreman.AssignTasksToClient(client_id)

    hunt_obj = aff4.FACTORY.Open(hunt_session_id, age=aff4.ALL_TIMES,
                                 token=self.token)
    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    # There should be only one client, due to the limit
    self.assertEqual(len(set(started)), 10)

  class MBRHuntMock(object):

    def ReadBuffer(self, args):

      response = rdfvalue.BufferReference(args)
      response.data = "\x01" * response.length

      return [response]

  def testMBRHunt(self):
    hunt = hunts.GRRHunt.StartHunt(
        "MBRHunt", length=3333,
        collect_replies=True,
        client_limit=1,
        token=self.token)
    hunt.Run()
    hunt.StartClient(hunt.session_id, self.client_id)

    # Run the hunt.
    client_mock = self.MBRHuntMock()
    test_lib.TestHuntHelper(client_mock, self.client_ids, False, self.token)

    mbr = aff4.FACTORY.Open(rdfvalue.RDFURN(self.client_id).Add("mbr"),
                            token=self.token)
    data = mbr.read(100000)
    self.assertEqual(len(data), 3333)

  def testCollectFilesHunt(self):
    fbc = [(c, [rdfvalue.PathSpec(path="/dir/file%d" % i, pathtype=0)])
           for i, c in enumerate(self.client_ids[:5])]
    hunt = hunts.GRRHunt.StartHunt(
        "CollectFilesHunt",
        files_by_client=dict(fbc),
        token=self.token)
    hunt.Run()
    hunt.ManuallyScheduleClients()

    # Run the hunt.
    client_mock = SampleHuntMock(failrate=len(self.client_ids))
    test_lib.TestHuntHelper(client_mock, self.client_ids, False, self.token)

    for i, c in enumerate(self.client_ids[:5]):
      fd = aff4.FACTORY.Open(rdfvalue.RDFURN(c).Add("fs/os/dir/file%d" % i),
                             token=self.token)
      self.assertTrue(isinstance(fd, aff4.HashImage))