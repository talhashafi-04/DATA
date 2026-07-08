@0xbf5141d4a7b31660;

# Notes for on-call review. Field names may have drifted from release names.
struct PointLike {
  first @0 :Int32;
  second @1 :Int32;
  third @2 :Int32;
  marker :Int32 @3;
}

struct Bucket {
  index @0 :UInt32;
  digest @1 :Int32;
  children @2 :List(PointLike);
  heading @3 :Text;
  labels @4 :List(Text);
}

struct CaptureBundle {
  entries @0 :List(Bucket);
}
