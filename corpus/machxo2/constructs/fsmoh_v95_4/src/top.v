module top (clk, go, abort, last, busy);
  input clk;
  input go;
  input abort;
  output last;
  reg last;
  output busy;
  reg busy;
  parameter S0 = 4'd1;
  parameter S1 = 4'd2;
  parameter S2 = 4'd4;
  parameter S3 = 4'd8;
  reg [3:0] st;
  reg [3:0] ns;
  always @(st or go or abort) begin
    ns = st;
    case (st)
      S0: if (abort) ns = S0; else if (go) ns = S1;
      S1: if (abort) ns = S0; else if (go) ns = S2;
      S2: if (abort) ns = S0; else if (go) ns = S3;
      S3: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always @(posedge clk) begin
    st <= ns;
    last <= (ns == S3);
    busy <= (ns != S0);
  end
endmodule
