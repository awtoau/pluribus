module top (clk, go, abort, last, busy);
  input [0:0] clk;
  input [0:0] go;
  input [0:0] abort;
  output [0:0] last;
  reg [0:0] last;
  output [0:0] busy;
  reg [0:0] busy;
  parameter S0 = 3'd0;
  parameter S1 = 3'd1;
  parameter S2 = 3'd2;
  parameter S3 = 3'd3;
  parameter S4 = 3'd4;
  parameter S5 = 3'd5;
  parameter S6 = 3'd6;
  parameter S7 = 3'd7;
  (* syn_encoding = "onehot" *) reg [2:0] st;
  reg [2:0] ns;
  always @(st or go or abort) begin
    ns = st;
    case (st)
      S0: if (abort) ns = S0; else if (go) ns = S1;
      S1: if (abort) ns = S0; else if (go) ns = S2;
      S2: if (abort) ns = S0; else if (go) ns = S3;
      S3: if (abort) ns = S0; else if (go) ns = S4;
      S4: if (abort) ns = S0; else if (go) ns = S5;
      S5: if (abort) ns = S0; else if (go) ns = S6;
      S6: if (abort) ns = S0; else if (go) ns = S7;
      S7: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always @(posedge clk) begin
    st <= ns;
    last <= (ns == S7);
    busy <= (ns != S0);
  end
endmodule
