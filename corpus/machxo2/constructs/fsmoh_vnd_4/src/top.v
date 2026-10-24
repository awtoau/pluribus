module top (clk, go, abort, last, busy);
  input [0:0] clk;
  input [0:0] go;
  input [0:0] abort;
  output [0:0] last;
  reg [0:0] last;
  output [0:0] busy;
  reg [0:0] busy;
  parameter S0 = 2'd0;
  parameter S1 = 2'd1;
  parameter S2 = 2'd2;
  parameter S3 = 2'd3;
  (* syn_encoding = "onehot" *) reg [1:0] st;
  reg [1:0] ns;
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
